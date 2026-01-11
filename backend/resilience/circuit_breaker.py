"""
Circuit breaker utility for resilience.
Prevents cascading failures by temporarily disabling calls to failing services.
"""
from enum import Enum
from datetime import datetime, timedelta
import logging
from typing import Dict

logger = logging.getLogger(__name__)


# Circuit breaker configuration constants
FAILURE_THRESHOLD = 3  # Trip breaker after N consecutive failures
OPEN_STATE_DURATION = 60  # Seconds to remain OPEN before transitioning to HALF_OPEN
HALF_OPEN_MAX_REQUESTS = 1  # Max requests allowed in HALF_OPEN state


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing fast, not calling upstream
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """
    Circuit breaker for protecting against cascading failures.
    
    State machine:
    - CLOSED: Normal operation, calls pass through
    - OPEN: Fail fast, no calls to upstream
    - HALF_OPEN: Allow limited test calls
    
    Transitions:
    - CLOSED -> OPEN: After FAILURE_THRESHOLD consecutive failures
    - OPEN -> HALF_OPEN: After OPEN_STATE_DURATION seconds
    - HALF_OPEN -> CLOSED: On successful request
    - HALF_OPEN -> OPEN: On failure during test
    """
    
    def __init__(
        self,
        service_name: str,
        failure_threshold: int = FAILURE_THRESHOLD,
        open_duration: int = OPEN_STATE_DURATION,
        half_open_max_requests: int = HALF_OPEN_MAX_REQUESTS
    ):
        """
        Initialize circuit breaker.
        
        Args:
            service_name: Name of the service (e.g., "mistral", "aws_pricing")
            failure_threshold: Number of consecutive failures before opening
            open_duration: Seconds to remain OPEN before HALF_OPEN
            half_open_max_requests: Max requests allowed in HALF_OPEN state
        """
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.open_duration = open_duration
        self.half_open_max_requests = half_open_max_requests
        
        # State tracking
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: datetime = None
        self.opened_at: datetime = None
        self.half_open_requests = 0
    
    def allow_request(self) -> bool:
        """
        Check if request should be allowed.
        
        Returns:
            True if request should proceed, False if circuit is open
        """
        now = datetime.now()
        
        # Handle state transitions
        if self.state == CircuitState.OPEN:
            # Check if we should transition to HALF_OPEN
            if self.opened_at and (now - self.opened_at).total_seconds() >= self.open_duration:
                logger.warning(
                    f"Circuit breaker for {self.service_name}: "
                    f"OPEN -> HALF_OPEN (testing recovery)"
                )
                self.state = CircuitState.HALF_OPEN
                self.half_open_requests = 0
                return True
            return False
        
        elif self.state == CircuitState.HALF_OPEN:
            # Allow limited requests in HALF_OPEN
            if self.half_open_requests < self.half_open_max_requests:
                self.half_open_requests += 1
                return True
            return False
        
        # CLOSED state: allow all requests
        return True
    
    def record_success(self) -> None:
        """
        Record a successful request.
        
        Resets failure count and transitions to CLOSED if in HALF_OPEN.
        """
        if self.state == CircuitState.HALF_OPEN:
            logger.warning(
                f"Circuit breaker for {self.service_name}: "
                f"HALF_OPEN -> CLOSED (service recovered)"
            )
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.half_open_requests = 0
            self.opened_at = None
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0
    
    def record_failure(self) -> None:
        """
        Record a failed request.
        
        Increments failure count and transitions to OPEN if threshold reached.
        """
        now = datetime.now()
        self.failure_count += 1
        self.last_failure_time = now
        
        if self.state == CircuitState.HALF_OPEN:
            # Failure in HALF_OPEN: return to OPEN
            logger.warning(
                f"Circuit breaker for {self.service_name}: "
                f"HALF_OPEN -> OPEN (service still failing)"
            )
            self.state = CircuitState.OPEN
            self.opened_at = now
            self.half_open_requests = 0
        elif self.state == CircuitState.CLOSED:
            # Check if we should open the circuit
            if self.failure_count >= self.failure_threshold:
                logger.warning(
                    f"Circuit breaker for {self.service_name}: "
                    f"CLOSED -> OPEN ({self.failure_count} consecutive failures)"
                )
                self.state = CircuitState.OPEN
                self.opened_at = now
    
    def current_state(self) -> CircuitState:
        """
        Get current circuit state.
        
        Returns:
            Current CircuitState
        """
        return self.state


# Global circuit breaker instances (one per service)
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(service_name: str) -> CircuitBreaker:
    """
    Get or create circuit breaker for a service.
    
    Args:
        service_name: Name of the service
    
    Returns:
        CircuitBreaker instance for the service
    """
    if service_name not in _circuit_breakers:
        _circuit_breakers[service_name] = CircuitBreaker(service_name)
    return _circuit_breakers[service_name]
