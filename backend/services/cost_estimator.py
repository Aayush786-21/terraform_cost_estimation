"""
Cost estimator service.
Converts intent graph into cost estimates using official pricing APIs.
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import logging

from backend.domain.cost_models import CostEstimate, CostLineItem, UnpricedResource
from backend.domain.scenario_models import ScenarioInput, ScenarioDeltaLineItem, ScenarioEstimateResult
from backend.pricing.aws_pricing_client import AWSPricingClient, AWSPricingError
from backend.pricing.aws_bulk_pricing import create_bulk_pricing_client, AWSBulkPricingClient
from backend.pricing.azure_pricing_client import AzurePricingClient, AzurePricingError
from backend.pricing.gcp_pricing_client import GCPPricingClient, GCPPricingError
from backend.core.config import config


logger = logging.getLogger(__name__)


class CostEstimatorError(Exception):
    """Raised when cost estimation fails."""
    pass


class CostEstimator:
    """Service for estimating costs from Terraform intent graph."""
    
    def __init__(
        self,
        aws_client: AWSPricingClient = None,
        azure_client: AzurePricingClient = None,
        gcp_client: GCPPricingClient = None
    ):
        """
        Initialize cost estimator with pricing clients.
        
        This constructor is intentionally defensive:
        - If a cloud pricing client cannot be initialized (e.g. missing SDK,
          no network, or credentials issues), we log the problem and fall back
          to static baseline prices for common instance types instead of
          failing the entire estimate.
        - This keeps the product usable in local/demo environments while still
          using official pricing APIs when available.
        
        Args:
            aws_client: AWS pricing client (creates new if None)
            azure_client: Azure pricing client (creates new if None)
            gcp_client: GCP pricing client (creates new if None)
        """
        # AWS client: Try bulk pricing first (fast, cached), then API client (slower, but works)
        # Bulk pricing is preferred for production use
        self.aws_bulk_client = create_bulk_pricing_client()
        if self.aws_bulk_client:
            logger.info("Using AWS bulk pricing client (cached offer files)")
            self.aws_client = None  # Don't need API client if bulk is available
        elif aws_client is not None:
            self.aws_client = aws_client
            self.aws_bulk_client = None
        else:
            try:
                self.aws_client = AWSPricingClient()
                self.aws_bulk_client = None
            except AWSPricingError as error:
                logger.warning(
                    "AWS pricing client unavailable, falling back to static pricing: %s",
                    error,
                )
                self.aws_client = None
                self.aws_bulk_client = None

        # Azure client (may fallback to static pricing)
        if azure_client is not None:
            self.azure_client = azure_client
        else:
            try:
                self.azure_client = AzurePricingClient()
            except AzurePricingError as error:
                logger.warning(
                    "Azure pricing client unavailable, falling back to static pricing: %s",
                    error,
                )
                self.azure_client = None

        # GCP client (currently a placeholder; pricing not fully implemented)
        try:
            self.gcp_client = gcp_client or GCPPricingClient()
        except GCPPricingError as error:
            logger.warning(
                "GCP pricing client unavailable (pricing not yet implemented): %s",
                error,
            )
            self.gcp_client = None
    
    def _resolve_region(
        self,
        region_info: Dict[str, Any],
        region_override: Optional[str] = None
    ) -> Tuple[str, List[str]]:
        """
        Resolve region from region_info, with optional override.
        
        Args:
            region_info: Region info from intent graph
            region_override: Optional region override from request
        
        Returns:
            Tuple of (resolved_region, assumptions_list)
        """
        assumptions = []
        
        if region_override:
            assumptions.append(f"Region overridden to {region_override}")
            return region_override, assumptions
        
        region_source = region_info.get("source", "unknown")
        region_value = region_info.get("value")
        
        # Handle explicit region (from resource) or provider_default (from provider config)
        if region_source in ["explicit", "provider_default"] and region_value:
            if region_source == "provider_default":
                assumptions.append(f"Region from provider config: {region_value}")
            return region_value, assumptions
        
        # Default region based on cloud provider
        # Could be enhanced to detect from provider config
        default_region = "us-east-1"  # Conservative default
        assumptions.append(f"Region not specified, using default: {default_region}")
        return default_region, assumptions
    
    def _resolve_count(
        self,
        count_model: Dict[str, Any],
        autoscaling_average_override: Optional[int] = None
    ) -> Tuple[Optional[int], List[str]]:
        """
        Resolve resource count from count_model.
        
        Args:
            count_model: Count model from intent graph
            autoscaling_average_override: Optional override for autoscaling average
        
        Returns:
            Tuple of (count_value, assumptions_list)
        """
        assumptions = []
        count_type = count_model.get("type", "unknown")
        
        if count_type == "fixed":
            value = count_model.get("value")
            if value is not None:
                return int(value), assumptions
            # Default to 1 for fixed resources without explicit count (single resource)
            assumptions.append("No count specified, assuming single resource (1)")
            return 1, assumptions
        
        elif count_type == "autoscaling":
            if autoscaling_average_override is not None:
                assumptions.append(f"Using provided autoscaling average: {autoscaling_average_override}")
                return autoscaling_average_override, assumptions
            
            # Try to use average of min/max if available
            min_val = count_model.get("min")
            max_val = count_model.get("max")
            if min_val is not None and max_val is not None:
                average = (min_val + max_val) / 2
                assumptions.append(f"Autoscaling: using average of min/max: {average}")
                return int(average), assumptions
            
            assumptions.append("Autoscaling: cannot determine average count")
            return None, assumptions
        
        else:
            # Default to 1 for unknown count types (single resources without count attribute)
            assumptions.append(f"Count type '{count_type}' not specified, assuming single resource (1)")
            return 1, assumptions
    
    async def _price_aws_resource(
        self,
        resource: Dict[str, Any],
        resolved_region: str,
        resolved_count: int,
        assumptions: List[str]
    ) -> Optional[CostLineItem]:
        """
        Price an AWS resource.
        
        Args:
            resource: Resource from intent graph
            resolved_region: Resolved region
            resolved_count: Resolved resource count
            assumptions: List of assumptions (mutated)
        
        Returns:
            CostLineItem if priced, None otherwise
        """
        service = resource.get("service", "")
        terraform_type = resource.get("terraform_type", "")
        resource_name = resource.get("name", "unknown")
        size_hint = resource.get("size", {})
        usage = resource.get("usage", {})
        count_model = resource.get("count_model", {})
        confidence = count_model.get("confidence", "low")
        
        # Handle free/low-cost resources (these don't have instance_type)
        # Comprehensive list of AWS services that are free or have no base charge
        free_resources = {
            # VPC & Networking (Free)
            "aws_vpc": ("VPC", "Free - VPCs have no charge"),
            "aws_subnet": ("VPC", "Free - Subnets have no charge"),
            "aws_internet_gateway": ("VPC", "Free - Internet gateways have no charge"),
            "aws_egress_only_internet_gateway": ("VPC", "Free - Egress-only internet gateways have no charge"),
            "aws_route_table": ("VPC", "Free - Route tables have no charge"),
            "aws_route_table_association": ("VPC", "Free - Route table associations have no charge"),
            "aws_route": ("VPC", "Free - Routes have no charge"),
            "aws_main_route_table_association": ("VPC", "Free - Main route table associations have no charge"),
            "aws_network_acl": ("VPC", "Free - Network ACLs have no charge"),
            "aws_network_acl_rule": ("VPC", "Free - Network ACL rules have no charge"),
            "aws_vpc_dhcp_options": ("VPC", "Free - DHCP options sets have no charge"),
            "aws_vpc_dhcp_options_association": ("VPC", "Free - DHCP options associations have no charge"),
            "aws_vpc_peering_connection": ("VPC", "Free - VPC peering connections have no charge"),
            "aws_vpc_peering_connection_accepter": ("VPC", "Free - VPC peering accepters have no charge"),
            "aws_vpc_endpoint_service": ("VPC", "Free - VPC endpoint services have no charge"),
            "aws_vpc_endpoint_route_table_association": ("VPC", "Free - VPC endpoint route table associations have no charge"),
            "aws_vpc_endpoint_subnet_association": ("VPC", "Free - VPC endpoint subnet associations have no charge"),
            "aws_vpc_ipv4_cidr_block_association": ("VPC", "Free - VPC IPv4 CIDR block associations have no charge"),
            "aws_customer_gateway": ("VPC", "Free - Customer gateways have no charge"),
            "aws_security_group": ("EC2", "Free - Security groups have no charge"),
            "aws_security_group_rule": ("EC2", "Free - Security group rules have no charge"),
            "aws_default_security_group": ("EC2", "Free - Default security groups have no charge"),
            "aws_default_vpc": ("VPC", "Free - Default VPCs have no charge"),
            "aws_default_subnet": ("VPC", "Free - Default subnets have no charge"),
            "aws_default_route_table": ("VPC", "Free - Default route tables have no charge"),
            "aws_default_network_acl": ("VPC", "Free - Default network ACLs have no charge"),
            
            # IAM (Free)
            "aws_iam_role": ("IAM", "Free - IAM roles have no charge"),
            "aws_iam_role_policy": ("IAM", "Free - IAM role policies have no charge"),
            "aws_iam_role_policy_attachment": ("IAM", "Free - IAM role policy attachments have no charge"),
            "aws_iam_policy": ("IAM", "Free - IAM policies have no charge"),
            "aws_iam_policy_attachment": ("IAM", "Free - IAM policy attachments have no charge"),
            "aws_iam_instance_profile": ("IAM", "Free - IAM instance profiles have no charge"),
            "aws_iam_user": ("IAM", "Free - IAM users have no charge"),
            "aws_iam_user_policy": ("IAM", "Free - IAM user policies have no charge"),
            "aws_iam_user_policy_attachment": ("IAM", "Free - IAM user policy attachments have no charge"),
            "aws_iam_user_group_membership": ("IAM", "Free - IAM user group memberships have no charge"),
            "aws_iam_group": ("IAM", "Free - IAM groups have no charge"),
            "aws_iam_group_policy": ("IAM", "Free - IAM group policies have no charge"),
            "aws_iam_group_policy_attachment": ("IAM", "Free - IAM group policy attachments have no charge"),
            "aws_iam_group_membership": ("IAM", "Free - IAM group memberships have no charge"),
            "aws_iam_access_key": ("IAM", "Free - IAM access keys have no charge"),
            "aws_iam_saml_provider": ("IAM", "Free - IAM SAML providers have no charge"),
            "aws_iam_openid_connect_provider": ("IAM", "Free - IAM OpenID Connect providers have no charge"),
            "aws_iam_server_certificate": ("IAM", "Free - IAM server certificates have no charge"),
            "aws_iam_service_linked_role": ("IAM", "Free - IAM service-linked roles have no charge"),
            
            # CloudWatch (Free tier available)
            "aws_cloudwatch_log_group": ("CloudWatch", "Free - CloudWatch Log Groups have no charge (pay for ingestion/storage)"),
            "aws_cloudwatch_log_stream": ("CloudWatch", "Free - CloudWatch Log Streams have no charge"),
            "aws_cloudwatch_log_metric_filter": ("CloudWatch", "Free - CloudWatch Log Metric Filters have no charge"),
            "aws_cloudwatch_log_destination": ("CloudWatch", "Free - CloudWatch Log Destinations have no charge"),
            "aws_cloudwatch_log_destination_policy": ("CloudWatch", "Free - CloudWatch Log Destination Policies have no charge"),
            "aws_cloudwatch_log_resource_policy": ("CloudWatch", "Free - CloudWatch Log Resource Policies have no charge"),
            "aws_cloudwatch_metric_alarm": ("CloudWatch", "Free - CloudWatch Metric Alarms have no charge"),
            "aws_cloudwatch_composite_alarm": ("CloudWatch", "Free - CloudWatch Composite Alarms have no charge"),
            "aws_cloudwatch_dashboard": ("CloudWatch", "Free - CloudWatch Dashboards have no charge"),
            "aws_cloudwatch_event_rule": ("CloudWatch", "Free - CloudWatch Event Rules have no charge (pay for targets)"),
            "aws_cloudwatch_event_target": ("CloudWatch", "Free - CloudWatch Event Targets have no charge"),
            "aws_cloudwatch_event_permission": ("CloudWatch", "Free - CloudWatch Event Permissions have no charge"),
            "aws_cloudwatch_event_bus": ("CloudWatch", "Free - CloudWatch Event Buses have no charge"),
            "aws_cloudwatch_event_archive": ("CloudWatch", "Free - CloudWatch Event Archives have no charge"),
            "aws_cloudwatch_event_connection": ("CloudWatch", "Free - CloudWatch Event Connections have no charge"),
            "aws_cloudwatch_event_api_destination": ("CloudWatch", "Free - CloudWatch Event API Destinations have no charge"),
            
            # CloudFormation (Free)
            "aws_cloudformation_stack": ("CloudFormation", "Free - CloudFormation stacks have no charge"),
            "aws_cloudformation_stack_set": ("CloudFormation", "Free - CloudFormation stack sets have no charge"),
            "aws_cloudformation_stack_set_instance": ("CloudFormation", "Free - CloudFormation stack set instances have no charge"),
            
            # Route 53 (Free tier available)
            "aws_route53_zone": ("Route53", "Free - Route 53 hosted zones have no charge (first zone free)"),
            "aws_route53_record": ("Route53", "Free - Route 53 records have no charge"),
            "aws_route53_health_check": ("Route53", "Free - Route 53 health checks have no charge (first 50 free)"),
            "aws_route53_delegation_set": ("Route53", "Free - Route 53 delegation sets have no charge"),
            "aws_route53_query_log": ("Route53", "Free - Route 53 query logs have no charge"),
            "aws_route53_vpc_association_authorization": ("Route53", "Free - Route 53 VPC association authorizations have no charge"),
            
            # SNS (Free tier available)
            "aws_sns_topic": ("SNS", "Free - SNS topics have no charge (pay for messages)"),
            "aws_sns_topic_policy": ("SNS", "Free - SNS topic policies have no charge"),
            "aws_sns_topic_subscription": ("SNS", "Free - SNS topic subscriptions have no charge"),
            
            # SQS (Free tier available)
            "aws_sqs_queue": ("SQS", "Free - SQS queues have no charge (pay for requests)"),
            "aws_sqs_queue_policy": ("SQS", "Free - SQS queue policies have no charge"),
            
            # EventBridge (Free tier available)
            "aws_cloudwatch_event_rule": ("EventBridge", "Free - EventBridge rules have no charge (pay for targets)"),
            "aws_cloudwatch_event_target": ("EventBridge", "Free - EventBridge targets have no charge"),
            "aws_cloudwatch_event_bus": ("EventBridge", "Free - EventBridge event buses have no charge"),
            
            # API Gateway (Free tier available)
            "aws_api_gateway_rest_api": ("API Gateway", "Free - API Gateway REST APIs have no charge (pay for requests)"),
            "aws_api_gateway_resource": ("API Gateway", "Free - API Gateway resources have no charge"),
            "aws_api_gateway_method": ("API Gateway", "Free - API Gateway methods have no charge"),
            "aws_api_gateway_integration": ("API Gateway", "Free - API Gateway integrations have no charge"),
            "aws_api_gateway_deployment": ("API Gateway", "Free - API Gateway deployments have no charge"),
            "aws_api_gateway_stage": ("API Gateway", "Free - API Gateway stages have no charge"),
            "aws_api_gateway_api_key": ("API Gateway", "Free - API Gateway API keys have no charge"),
            "aws_api_gateway_usage_plan": ("API Gateway", "Free - API Gateway usage plans have no charge"),
            "aws_api_gateway_usage_plan_key": ("API Gateway", "Free - API Gateway usage plan keys have no charge"),
            "aws_api_gateway_method_response": ("API Gateway", "Free - API Gateway method responses have no charge"),
            "aws_api_gateway_integration_response": ("API Gateway", "Free - API Gateway integration responses have no charge"),
            "aws_api_gateway_gateway_response": ("API Gateway", "Free - API Gateway gateway responses have no charge"),
            "aws_api_gateway_model": ("API Gateway", "Free - API Gateway models have no charge"),
            "aws_api_gateway_request_validator": ("API Gateway", "Free - API Gateway request validators have no charge"),
            "aws_api_gateway_base_path_mapping": ("API Gateway", "Free - API Gateway base path mappings have no charge"),
            "aws_api_gateway_vpc_link": ("API Gateway", "Free - API Gateway VPC links have no charge"),
            "aws_api_gateway_authorizer": ("API Gateway", "Free - API Gateway authorizers have no charge"),
            "aws_api_gateway_account": ("API Gateway", "Free - API Gateway accounts have no charge"),
            "aws_api_gateway_client_certificate": ("API Gateway", "Free - API Gateway client certificates have no charge"),
            "aws_api_gateway_documentation_part": ("API Gateway", "Free - API Gateway documentation parts have no charge"),
            "aws_api_gateway_documentation_version": ("API Gateway", "Free - API Gateway documentation versions have no charge"),
            "aws_api_gateway_response": ("API Gateway", "Free - API Gateway responses have no charge"),
            
            # Certificate Manager (Free)
            "aws_acm_certificate": ("ACM", "Free - ACM certificates have no charge"),
            "aws_acm_certificate_validation": ("ACM", "Free - ACM certificate validations have no charge"),
            
            # Secrets Manager (Free tier available)
            "aws_secretsmanager_secret": ("Secrets Manager", "Free - Secrets Manager secrets have no charge (pay for API calls)"),
            "aws_secretsmanager_secret_version": ("Secrets Manager", "Free - Secrets Manager secret versions have no charge"),
            
            # Systems Manager (Free tier available)
            "aws_ssm_parameter": ("Systems Manager", "Free - SSM parameters have no charge (Standard tier free)"),
            "aws_ssm_document": ("Systems Manager", "Free - SSM documents have no charge"),
            "aws_ssm_association": ("Systems Manager", "Free - SSM associations have no charge"),
            "aws_ssm_maintenance_window": ("Systems Manager", "Free - SSM maintenance windows have no charge"),
            "aws_ssm_maintenance_window_target": ("Systems Manager", "Free - SSM maintenance window targets have no charge"),
            "aws_ssm_maintenance_window_task": ("Systems Manager", "Free - SSM maintenance window tasks have no charge"),
            "aws_ssm_patch_baseline": ("Systems Manager", "Free - SSM patch baselines have no charge"),
            "aws_ssm_patch_group": ("Systems Manager", "Free - SSM patch groups have no charge"),
            
            # CloudTrail (Free tier available)
            "aws_cloudtrail": ("CloudTrail", "Free - CloudTrail trails have no charge (first trail free)"),
            
            # Config (Free tier available)
            "aws_config_configuration_recorder": ("Config", "Free - Config recorders have no charge"),
            "aws_config_delivery_channel": ("Config", "Free - Config delivery channels have no charge"),
            "aws_config_config_rule": ("Config", "Free - Config rules have no charge"),
            "aws_config_configuration_aggregator": ("Config", "Free - Config aggregators have no charge"),
            "aws_config_aggregate_authorization": ("Config", "Free - Config aggregate authorizations have no charge"),
            "aws_config_organization_custom_rule": ("Config", "Free - Config organization custom rules have no charge"),
            "aws_config_organization_managed_rule": ("Config", "Free - Config organization managed rules have no charge"),
            
            # KMS (Free tier available)
            "aws_kms_key": ("KMS", "Free - KMS keys have no charge (pay for API calls)"),
            "aws_kms_alias": ("KMS", "Free - KMS aliases have no charge"),
            "aws_kms_grant": ("KMS", "Free - KMS grants have no charge"),
            "aws_kms_ciphertext": ("KMS", "Free - KMS ciphertexts have no charge"),
            "aws_kms_external_key": ("KMS", "Free - KMS external keys have no charge"),
            "aws_kms_replica_key": ("KMS", "Free - KMS replica keys have no charge"),
            "aws_kms_replica_external_key": ("KMS", "Free - KMS replica external keys have no charge"),
            
            # Lambda Layers (Free)
            "aws_lambda_layer_version": ("Lambda", "Free - Lambda layers have no charge"),
            "aws_lambda_permission": ("Lambda", "Free - Lambda permissions have no charge"),
            "aws_lambda_event_source_mapping": ("Lambda", "Free - Lambda event source mappings have no charge"),
            "aws_lambda_function_event_invoke_config": ("Lambda", "Free - Lambda function event invoke configs have no charge"),
            "aws_lambda_code_signing_config": ("Lambda", "Free - Lambda code signing configs have no charge"),
            "aws_lambda_alias": ("Lambda", "Free - Lambda aliases have no charge"),
            
            # Step Functions (Free tier available)
            "aws_sfn_state_machine": ("Step Functions", "Free - Step Functions state machines have no charge (pay for executions)"),
            "aws_sfn_activity": ("Step Functions", "Free - Step Functions activities have no charge"),
            
            # Cognito (Free tier available)
            "aws_cognito_user_pool": ("Cognito", "Free - Cognito user pools have no charge (pay for MAUs)"),
            "aws_cognito_user_pool_client": ("Cognito", "Free - Cognito user pool clients have no charge"),
            "aws_cognito_user_pool_domain": ("Cognito", "Free - Cognito user pool domains have no charge"),
            "aws_cognito_identity_pool": ("Cognito", "Free - Cognito identity pools have no charge"),
            "aws_cognito_identity_provider": ("Cognito", "Free - Cognito identity providers have no charge"),
            "aws_cognito_user_group": ("Cognito", "Free - Cognito user groups have no charge"),
            "aws_cognito_user_pool_ui_customization": ("Cognito", "Free - Cognito UI customizations have no charge"),
            
            # SES (Free tier available)
            "aws_ses_domain_identity": ("SES", "Free - SES domain identities have no charge"),
            "aws_ses_email_identity": ("SES", "Free - SES email identities have no charge"),
            "aws_ses_domain_identity_verification": ("SES", "Free - SES domain identity verifications have no charge"),
            "aws_ses_email_identity_verification": ("SES", "Free - SES email identity verifications have no charge"),
            "aws_ses_configuration_set": ("SES", "Free - SES configuration sets have no charge"),
            "aws_ses_event_destination": ("SES", "Free - SES event destinations have no charge"),
            "aws_ses_identity_policy": ("SES", "Free - SES identity policies have no charge"),
            "aws_ses_receipt_rule": ("SES", "Free - SES receipt rules have no charge"),
            "aws_ses_receipt_rule_set": ("SES", "Free - SES receipt rule sets have no charge"),
            "aws_ses_template": ("SES", "Free - SES templates have no charge"),
            
            # CloudFront (Free tier available)
            "aws_cloudfront_distribution": ("CloudFront", "Free - CloudFront distributions have no charge (pay for data transfer)"),
            "aws_cloudfront_origin_access_identity": ("CloudFront", "Free - CloudFront origin access identities have no charge"),
            "aws_cloudfront_origin_access_control": ("CloudFront", "Free - CloudFront origin access controls have no charge"),
            "aws_cloudfront_public_key": ("CloudFront", "Free - CloudFront public keys have no charge"),
            "aws_cloudfront_key_group": ("CloudFront", "Free - CloudFront key groups have no charge"),
            "aws_cloudfront_cache_policy": ("CloudFront", "Free - CloudFront cache policies have no charge"),
            "aws_cloudfront_response_headers_policy": ("CloudFront", "Free - CloudFront response headers policies have no charge"),
            "aws_cloudfront_realtime_log_config": ("CloudFront", "Free - CloudFront realtime log configs have no charge"),
            "aws_cloudfront_monitoring_subscription": ("CloudFront", "Free - CloudFront monitoring subscriptions have no charge"),
            "aws_cloudfront_origin_request_policy": ("CloudFront", "Free - CloudFront origin request policies have no charge"),
            "aws_cloudfront_field_level_encryption_config": ("CloudFront", "Free - CloudFront field level encryption configs have no charge"),
            "aws_cloudfront_field_level_encryption_profile": ("CloudFront", "Free - CloudFront field level encryption profiles have no charge"),
            
            # WAF (Free tier available)
            "aws_waf_web_acl": ("WAF", "Free - WAF web ACLs have no charge (pay for requests)"),
            "aws_waf_rule": ("WAF", "Free - WAF rules have no charge"),
            "aws_waf_rule_group": ("WAF", "Free - WAF rule groups have no charge"),
            "aws_waf_ipset": ("WAF", "Free - WAF IP sets have no charge"),
            "aws_waf_byte_match_set": ("WAF", "Free - WAF byte match sets have no charge"),
            "aws_waf_size_constraint_set": ("WAF", "Free - WAF size constraint sets have no charge"),
            "aws_waf_sql_injection_match_set": ("WAF", "Free - WAF SQL injection match sets have no charge"),
            "aws_waf_xss_match_set": ("WAF", "Free - WAF XSS match sets have no charge"),
            "aws_waf_geo_match_set": ("WAF", "Free - WAF geo match sets have no charge"),
            "aws_waf_regex_match_set": ("WAF", "Free - WAF regex match sets have no charge"),
            "aws_waf_rate_based_rule": ("WAF", "Free - WAF rate-based rules have no charge"),
            "aws_waf_regex_pattern_set": ("WAF", "Free - WAF regex pattern sets have no charge"),
            
            # Shield (Free tier available)
            "aws_shield_protection": ("Shield", "Free - Shield protections have no charge (Standard tier free)"),
            "aws_shield_protection_group": ("Shield", "Free - Shield protection groups have no charge"),
            "aws_shield_protection_health_check_association": ("Shield", "Free - Shield protection health check associations have no charge"),
            
            # ECS (Free - pay for underlying resources)
            "aws_ecs_cluster": ("ECS", "Free - ECS clusters have no charge (pay for tasks/services)"),
            "aws_ecs_service": ("ECS", "Free - ECS services have no charge (pay for tasks)"),
            "aws_ecs_task_definition": ("ECS", "Free - ECS task definitions have no charge"),
            "aws_ecs_capacity_provider": ("ECS", "Free - ECS capacity providers have no charge"),
            "aws_ecs_cluster_capacity_providers": ("ECS", "Free - ECS cluster capacity providers have no charge"),
            "aws_ecs_task_set": ("ECS", "Free - ECS task sets have no charge"),
            
            # ECR (Free tier available)
            "aws_ecr_repository": ("ECR", "Free - ECR repositories have no charge (pay for storage)"),
            "aws_ecr_lifecycle_policy": ("ECR", "Free - ECR lifecycle policies have no charge"),
            "aws_ecr_repository_policy": ("ECR", "Free - ECR repository policies have no charge"),
            "aws_ecr_replication_configuration": ("ECR", "Free - ECR replication configurations have no charge"),
            "aws_ecr_registry_policy": ("ECR", "Free - ECR registry policies have no charge"),
            "aws_ecr_pull_through_cache_rule": ("ECR", "Free - ECR pull through cache rules have no charge"),
            
            # CodeCommit (Free tier available)
            "aws_codecommit_repository": ("CodeCommit", "Free - CodeCommit repositories have no charge (pay for storage/requests)"),
            "aws_codecommit_trigger": ("CodeCommit", "Free - CodeCommit triggers have no charge"),
            "aws_codecommit_approval_rule_template": ("CodeCommit", "Free - CodeCommit approval rule templates have no charge"),
            "aws_codecommit_approval_rule_template_association": ("CodeCommit", "Free - CodeCommit approval rule template associations have no charge"),
            
            # CodeBuild (Free tier available)
            "aws_codebuild_project": ("CodeBuild", "Free - CodeBuild projects have no charge (pay for build minutes)"),
            "aws_codebuild_report_group": ("CodeBuild", "Free - CodeBuild report groups have no charge"),
            "aws_codebuild_source_credential": ("CodeBuild", "Free - CodeBuild source credentials have no charge"),
            "aws_codebuild_webhook": ("CodeBuild", "Free - CodeBuild webhooks have no charge"),
            
            # CodeDeploy (Free)
            "aws_codedeploy_app": ("CodeDeploy", "Free - CodeDeploy applications have no charge"),
            "aws_codedeploy_deployment_group": ("CodeDeploy", "Free - CodeDeploy deployment groups have no charge"),
            "aws_codedeploy_deployment_config": ("CodeDeploy", "Free - CodeDeploy deployment configs have no charge"),
            
            # CodePipeline (Free tier available)
            "aws_codepipeline": ("CodePipeline", "Free - CodePipeline pipelines have no charge (pay for actions)"),
            "aws_codepipeline_webhook": ("CodePipeline", "Free - CodePipeline webhooks have no charge"),
            
            # DynamoDB (Free tier available)
            "aws_dynamodb_table_item": ("DynamoDB", "Free - DynamoDB table items have no charge"),
            "aws_dynamodb_tag": ("DynamoDB", "Free - DynamoDB tags have no charge"),
            
            # AppSync (Free tier available)
            "aws_appsync_graphql_api": ("AppSync", "Free - AppSync GraphQL APIs have no charge (pay for requests)"),
            "aws_appsync_api_key": ("AppSync", "Free - AppSync API keys have no charge"),
            "aws_appsync_datasource": ("AppSync", "Free - AppSync datasources have no charge"),
            "aws_appsync_function": ("AppSync", "Free - AppSync functions have no charge"),
            "aws_appsync_resolver": ("AppSync", "Free - AppSync resolvers have no charge"),
            
            # Amplify (Free tier available)
            "aws_amplify_app": ("Amplify", "Free - Amplify apps have no charge (pay for hosting)"),
            "aws_amplify_branch": ("Amplify", "Free - Amplify branches have no charge"),
            "aws_amplify_domain_association": ("Amplify", "Free - Amplify domain associations have no charge"),
            
            # Pinpoint (Free tier available)
            "aws_pinpoint_app": ("Pinpoint", "Free - Pinpoint apps have no charge (pay for messages)"),
            "aws_pinpoint_adm_channel": ("Pinpoint", "Free - Pinpoint ADM channels have no charge"),
            "aws_pinpoint_apns_channel": ("Pinpoint", "Free - Pinpoint APNS channels have no charge"),
            "aws_pinpoint_apns_sandbox_channel": ("Pinpoint", "Free - Pinpoint APNS sandbox channels have no charge"),
            "aws_pinpoint_apns_voip_channel": ("Pinpoint", "Free - Pinpoint APNS VoIP channels have no charge"),
            "aws_pinpoint_apns_voip_sandbox_channel": ("Pinpoint", "Free - Pinpoint APNS VoIP sandbox channels have no charge"),
            "aws_pinpoint_baidu_channel": ("Pinpoint", "Free - Pinpoint Baidu channels have no charge"),
            "aws_pinpoint_email_channel": ("Pinpoint", "Free - Pinpoint email channels have no charge"),
            "aws_pinpoint_event_stream": ("Pinpoint", "Free - Pinpoint event streams have no charge"),
            "aws_pinpoint_gcm_channel": ("Pinpoint", "Free - Pinpoint GCM channels have no charge"),
            "aws_pinpoint_sms_channel": ("Pinpoint", "Free - Pinpoint SMS channels have no charge"),
        }
        
        if terraform_type in free_resources:
            service_name, reason = free_resources[terraform_type]
            assumptions.append(reason)
            return CostLineItem(
                cloud="aws",
                service=service_name,
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=0.0,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="high"
            )
        
        # Handle Lambda functions (request-based pricing, not instance-based)
        is_lambda = (
            terraform_type == "aws_lambda_function"
            or terraform_type.startswith("aws_lambda_")
            or service.upper() == "LAMBDA"
            or "LAMBDA" in service.upper()
            or (terraform_type and "lambda" in terraform_type.lower())
        )
        
        if is_lambda:
            try:
                # Lambda pricing is based on:
                # 1. Requests: $0.20 per 1M requests (first 1M free per month)
                # 2. Compute: $0.0000166667 per GB-second (128 MB minimum)
                # 
                # Default assumptions for a basic Lambda function:
                # - 1M requests/month (first 1M are free)
                # - 128 MB memory
                # - 100ms average duration
                # - 1 GB-second per request = 0.128 GB × 0.1 seconds
                
                requests_per_month = usage.get("requests_per_month", 1000000)  # Default: 1M requests
                memory_mb = usage.get("memory_mb", 128)  # Default: 128 MB
                duration_ms = usage.get("duration_ms", 100)  # Default: 100ms
                
                assumptions.append(f"Lambda function with {memory_mb} MB memory")
                assumptions.append(f"Estimated {requests_per_month:,} requests/month")
                assumptions.append(f"Estimated {duration_ms}ms average duration")
                assumptions.append("Lambda pricing: $0.20 per 1M requests (first 1M free) + compute time")
                
                # Request pricing: $0.20 per 1M requests, first 1M free
                billable_requests = max(0, requests_per_month - 1000000)
                request_cost = (billable_requests / 1000000) * 0.20
                
                # Compute pricing: $0.0000166667 per GB-second
                # GB-seconds = (memory_mb / 1024) * (duration_ms / 1000) * requests
                memory_gb = memory_mb / 1024
                duration_seconds = duration_ms / 1000
                gb_seconds = memory_gb * duration_seconds * requests_per_month
                compute_cost = gb_seconds * 0.0000166667
                
                total_monthly_cost = request_cost + compute_cost
                
                return CostLineItem(
                    cloud="aws",
                    service="Lambda",
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    region=resolved_region,
                    monthly_cost_usd=total_monthly_cost * resolved_count,
                    pricing_unit="month",
                    assumptions=assumptions,
                    priced=True,
                    confidence="low"  # Low confidence because Lambda costs are highly usage-dependent
                )
            except Exception as error:
                logger.warning(f"Error calculating Lambda pricing for {resource_name}: {error}", exc_info=True)
                # Return a minimal cost estimate even if calculation fails
                return CostLineItem(
                    cloud="aws",
                    service="Lambda",
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    region=resolved_region,
                    monthly_cost_usd=0.01 * resolved_count,  # Minimal estimate
                    pricing_unit="month",
                    assumptions=assumptions + [f"Lambda pricing calculation had an error, using minimal estimate"],
                    priced=True,
                    confidence="low"
                )
        
        # Handle S3 buckets (storage-based pricing, not instance-based)
        # Check multiple variations of S3 identification
        is_s3 = (
            terraform_type == "aws_s3_bucket" 
            or terraform_type.startswith("aws_s3_")
            or service.upper() == "S3"
            or "S3" in service.upper()
            or (terraform_type and "s3" in terraform_type.lower())
        )
        
        if is_s3:
            try:
                # S3 pricing is based on storage, requests, and data transfer
                # For a basic bucket estimate, we'll use a minimal storage assumption
                # Default: 1 GB storage (first 50 GB are free in standard tier, but we'll estimate minimal cost)
                storage_gb = usage.get("storage_gb", 1.0)
                assumptions.append(f"S3 bucket with estimated {storage_gb} GB storage")
                assumptions.append("S3 pricing varies by storage class, requests, and data transfer")
                assumptions.append("This is a minimal estimate - actual costs depend on usage patterns")
                
                # Basic S3 Standard storage pricing (approximate, varies by region)
                # First 50 TB: ~$0.023 per GB/month in us-east-1
                # For minimal estimate, use a small fixed cost
                # Note: First 50 GB of standard storage is free, but we'll estimate for potential growth
                monthly_cost = max(0.0, (storage_gb - 50) * 0.023) if storage_gb > 50 else 0.0
                
                # Add minimal request costs (very small for basic usage)
                # PUT requests: ~$0.005 per 1,000 requests
                # GET requests: ~$0.0004 per 1,000 requests
                # For a basic bucket, assume minimal requests
                requests_per_month = usage.get("requests_per_month", 1000)
                request_cost = (requests_per_month / 1000) * 0.001  # Minimal estimate
                
                total_monthly_cost = monthly_cost + request_cost
                
                return CostLineItem(
                    cloud="aws",
                    service="S3",
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    region=resolved_region,
                    monthly_cost_usd=total_monthly_cost * resolved_count,
                    pricing_unit="month",
                    assumptions=assumptions,
                    priced=True,
                    confidence="low"  # Low confidence because S3 costs are highly usage-dependent
                )
            except Exception as error:
                logger.error(f"Error calculating S3 pricing for {resource_name}: {error}", exc_info=True)
                # Return a minimal cost estimate even if calculation fails
                return CostLineItem(
                    cloud="aws",
                    service="S3",
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    region=resolved_region,
                    monthly_cost_usd=0.01 * resolved_count,  # Minimal estimate
                    pricing_unit="month",
                    assumptions=assumptions + [f"S3 pricing calculation had an error, using minimal estimate"],
                    priced=True,
                    confidence="low"
            )
        
        # Special handling for NAT Gateway
        if terraform_type == "aws_nat_gateway":
            # NAT Gateway pricing: ~$0.045/hour + data processing (~$0.045/GB)
            # Base cost: $0.045/hour * 730 hours/month = ~$32.85/month
            # Plus data transfer costs (estimated based on usage)
            data_transfer_gb = usage.get("data_transfer_gb", 0)
            if data_transfer_gb == 0:
                # Default assumption: minimal data transfer (1 GB/month for idle/light usage)
                # This represents minimal outbound traffic through NAT Gateway
                data_transfer_gb = 1.0
                assumptions.append("Assuming minimal data transfer: 1 GB/month (idle/light usage scenario)")
                assumptions.append("This represents outbound internet traffic from private subnets through NAT Gateway")
                assumptions.append("Actual costs increase with data transfer volume - estimate for low-traffic scenario")
            
            hourly_cost = 0.045  # Base NAT Gateway hourly cost
            monthly_base = hourly_cost * 730  # ~$32.85/month
            data_processing_cost = data_transfer_gb * 0.045  # $0.045 per GB processed
            
            total_monthly_cost = (monthly_base + data_processing_cost) * resolved_count
            
            assumptions.append(f"NAT Gateway installation/base cost: ${hourly_cost:.4f}/hour × 730 hours = ${monthly_base:.2f}/month")
            assumptions.append(f"Data processing charges: {data_transfer_gb} GB × $0.045/GB = ${data_processing_cost:.2f}")
            assumptions.append("Note: Data transfer costs scale with actual usage - this assumes minimal traffic")
            
            return CostLineItem(
                cloud="aws",
                service="VPC",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="medium"  # Medium confidence - base cost is fixed, data transfer varies
            )
        
        # Special handling for Network Load Balancer (NLB)
        if terraform_type == "aws_lb" and service.lower() in ["nlb", "network load balancer"]:
            # NLB pricing: ~$0.0225/hour + NLCU charges
            # Base cost: $0.0225/hour * 730 hours/month = ~$16.43/month
            # NLCU charges: ~$0.006 per NLCU-hour (varies by usage)
            # Default assumption: 1 NLCU for minimal traffic
            nlcu_count = usage.get("nlcu_count", 1.0)
            if nlcu_count == 0:
                nlcu_count = 1.0
                assumptions.append("Assuming minimal NLCU usage: 1 NLCU (~1 Gbps, minimal connections)")
            
            hourly_cost = 0.0225  # Base NLB hourly cost
            monthly_base = hourly_cost * 730  # ~$16.43/month
            nlcu_hourly_cost = 0.006  # Per NLCU-hour
            nlcu_monthly_cost = nlcu_count * nlcu_hourly_cost * 730  # NLCU charges
            
            total_monthly_cost = (monthly_base + nlcu_monthly_cost) * resolved_count
            
            assumptions.append(f"NLB base cost: ${hourly_cost:.4f}/hour × 730 hours = ${monthly_base:.2f}/month")
            assumptions.append(f"NLCU charges: {nlcu_count} NLCU × ${nlcu_hourly_cost:.3f}/NLCU-hour × 730 hours = ${nlcu_monthly_cost:.2f}/month")
            assumptions.append("NLCU factors: processed bytes, active connections")
            assumptions.append("Note: Actual NLCU costs vary significantly with traffic - this assumes minimal usage")
            
            return CostLineItem(
                cloud="aws",
                service="ELB",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"  # Low confidence - NLCU costs vary greatly with traffic
            )
        
        # Special handling for Application Load Balancer (ALB)
        # aws_lb can be ALB, NLB, or CLB - we'll price as ALB by default
        if terraform_type == "aws_lb":
            # ALB pricing: ~$0.0225/hour + LCU charges
            # Base cost: $0.0225/hour * 730 hours/month = ~$16.43/month
            # LCU charges: ~$0.008 per LCU-hour (varies by usage)
            # Default assumption: 1 LCU for minimal traffic (1 user, 1 Mbps, etc.)
            lcu_count = usage.get("lcu_count", 1.0)
            if lcu_count == 0:
                lcu_count = 1.0
                assumptions.append("Assuming minimal LCU usage: 1 LCU (1 user, ~1 Mbps, minimal requests)")
            
            hourly_cost = 0.0225  # Base ALB hourly cost
            monthly_base = hourly_cost * 730  # ~$16.43/month
            lcu_hourly_cost = 0.008  # Per LCU-hour
            lcu_monthly_cost = lcu_count * lcu_hourly_cost * 730  # LCU charges
            
            total_monthly_cost = (monthly_base + lcu_monthly_cost) * resolved_count
            
            assumptions.append(f"ALB base cost: ${hourly_cost:.4f}/hour × 730 hours = ${monthly_base:.2f}/month")
            assumptions.append(f"LCU charges: {lcu_count} LCU × ${lcu_hourly_cost:.3f}/LCU-hour × 730 hours = ${lcu_monthly_cost:.2f}/month")
            assumptions.append("LCU factors: new connections, active connections, processed bytes, rule evaluations")
            assumptions.append("Note: Actual LCU costs vary significantly with traffic - this assumes minimal usage")
            
            return CostLineItem(
                cloud="aws",
                service="ELB",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"  # Low confidence - LCU costs vary greatly with traffic
            )
        
        # Special handling for Autoscaling Group
        if terraform_type == "aws_autoscaling_group":
            # ASG itself is free - it's just a management service
            # The cost comes from the EC2 instances it manages
            # If ASG is not triggered (scaling hasn't happened), cost is based on minimum instances
            min_size = count_model.get("min", 1)
            max_size = count_model.get("max", 1)
            desired_capacity = count_model.get("desired", min_size)
            
            assumptions.append(f"ASG is a free management service - cost comes from managed EC2 instances")
            assumptions.append(f"ASG configuration: min={min_size}, max={max_size}, desired={desired_capacity}")
            
            # Try to get instance type from size_hint (might be extracted from launch template)
            instance_type_from_hint = size_hint.get("instance_type")
            
            if instance_type_from_hint:
                # We have instance type - try to price it
                try:
                    if self.aws_client:
                        hourly_price = await self.aws_client.get_ec2_instance_price(
                            instance_type_from_hint,
                            resolved_region
                        )
                        if hourly_price:
                            # If ASG is not triggered, cost = min_size instances running 24/7
                            instances_running = min_size  # When not triggered, min instances run
                            monthly_cost = hourly_price * 730 * instances_running
                            
                            assumptions.append(f"If ASG is not triggered: {instances_running} instance(s) running at min capacity")
                            assumptions.append(f"Instance type: {instance_type_from_hint} @ ${hourly_price:.4f}/hour")
                            assumptions.append(f"Cost: {instances_running} × ${hourly_price:.4f}/hour × 730 hours = ${monthly_cost:.2f}/month")
                            assumptions.append("Note: If ASG scales up, cost increases based on actual instance count")
                            
                            return CostLineItem(
                                cloud="aws",
                                service="EC2",
                                resource_name=resource_name,
                                terraform_type=terraform_type,
                                region=resolved_region,
                                monthly_cost_usd=monthly_cost,
                                pricing_unit="month",
                                assumptions=assumptions,
                                priced=True,
                                confidence="medium"  # Medium - depends on whether ASG triggers
                            )
                except Exception as error:
                    logger.debug(f"Could not price ASG instances for {resource_name}: {error}")
            
            # Fallback: ASG service is free, but note about instance costs
            assumptions.append("Note: ASG cost = cost of managed EC2 instances (priced separately via launch template)")
            assumptions.append(f"If ASG is not triggered, cost is based on {min_size} minimum instance(s)")
            assumptions.append("Actual cost depends on instance types in launch template/configuration")
            
            return CostLineItem(
                cloud="aws",
                service="EC2",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=0.0,  # ASG service is free, instances priced separately
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"  # Low - can't price without instance type
            )
        
        # Special handling for VPC Endpoints (Interface)
        if terraform_type == "aws_vpc_endpoint" and service.lower() in ["vpc", "endpoint"]:
            # VPC Interface Endpoint pricing: ~$0.01/hour + data processing (~$0.01/GB)
            # Base cost: $0.01/hour * 730 hours/month = ~$7.30/month
            # Plus data processing costs
            data_transfer_gb = usage.get("data_transfer_gb", 0)
            if data_transfer_gb == 0:
                data_transfer_gb = 1.0
                assumptions.append("Assuming minimal data transfer: 1 GB/month (idle/light usage)")
            
            hourly_cost = 0.01  # Base VPC Endpoint hourly cost
            monthly_base = hourly_cost * 730  # ~$7.30/month
            data_processing_cost = data_transfer_gb * 0.01  # $0.01 per GB processed
            
            total_monthly_cost = (monthly_base + data_processing_cost) * resolved_count
            
            assumptions.append(f"VPC Interface Endpoint base cost: ${hourly_cost:.4f}/hour × 730 hours = ${monthly_base:.2f}/month")
            assumptions.append(f"Data processing: {data_transfer_gb} GB × $0.01/GB = ${data_processing_cost:.2f}")
            assumptions.append("Note: Gateway endpoints (S3, DynamoDB) are free - this is for Interface endpoints")
            assumptions.append("Actual costs depend on data transfer volume - this assumes minimal traffic")
            
            return CostLineItem(
                cloud="aws",
                service="VPC",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="medium"
            )
        
        # Special handling for EBS Volumes
        if terraform_type == "aws_ebs_volume":
            # EBS pricing: storage cost + IOPS (if provisioned)
            # gp3: ~$0.08/GB/month (default)
            # gp2: ~$0.10/GB/month
            # io1/io2: ~$0.125/GB/month + IOPS charges
            volume_type = size_hint.get("volume_type", "gp3")
            size_gb = usage.get("storage_gb", 20.0)  # Default 20 GB
            if size_gb == 0:
                size_gb = 20.0
                assumptions.append("Assuming default volume size: 20 GB (actual size may vary)")
            
            # Base storage pricing per GB/month
            storage_prices = {
                "gp3": 0.08,
                "gp2": 0.10,
                "io1": 0.125,
                "io2": 0.125,
                "st1": 0.045,
                "sc1": 0.015
            }
            price_per_gb = storage_prices.get(volume_type.lower(), 0.08)
            
            monthly_storage_cost = size_gb * price_per_gb
            
            # Add IOPS charges for provisioned IOPS volumes
            iops_cost = 0
            if volume_type.lower() in ["io1", "io2"]:
                provisioned_iops = usage.get("iops", 3000)  # Default 3000 IOPS
                if provisioned_iops == 0:
                    provisioned_iops = 3000
                    assumptions.append("Assuming default provisioned IOPS: 3000 IOPS")
                iops_cost = provisioned_iops * 0.065 / 1000  # $0.065 per 1000 IOPS/month
                assumptions.append(f"Provisioned IOPS: {provisioned_iops} × $0.065/1000 IOPS = ${iops_cost:.2f}/month")
            
            total_monthly_cost = (monthly_storage_cost + iops_cost) * resolved_count
            
            assumptions.append(f"EBS Volume type: {volume_type.upper()}")
            assumptions.append(f"Storage: {size_gb} GB × ${price_per_gb:.3f}/GB = ${monthly_storage_cost:.2f}/month")
            assumptions.append("Note: Actual costs depend on volume size and IOPS configuration")
            
            return CostLineItem(
                cloud="aws",
                service="EBS",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="medium"
            )
        
        # Special handling for EFS (Elastic File System)
        if terraform_type == "aws_efs_file_system":
            # EFS pricing: storage cost + throughput (if provisioned)
            # Standard: ~$0.30/GB/month
            # One Zone: ~$0.16/GB/month
            # Infrequent Access: ~$0.025/GB/month (storage) + $0.01/GB (retrieval)
            performance_mode = size_hint.get("performance_mode", "generalPurpose")
            storage_gb = usage.get("storage_gb", 10.0)  # Default 10 GB
            if storage_gb == 0:
                storage_gb = 10.0
                assumptions.append("Assuming default storage: 10 GB (actual usage may vary)")
            
            # Base storage pricing
            if "oneZone" in performance_mode.lower():
                price_per_gb = 0.16
            else:
                price_per_gb = 0.30  # Standard
            
            monthly_storage_cost = storage_gb * price_per_gb
            
            # Add provisioned throughput cost if specified
            throughput_cost = 0
            provisioned_throughput = usage.get("provisioned_throughput_mbps", 0)
            if provisioned_throughput > 0:
                throughput_cost = provisioned_throughput * 0.05 * 730  # $0.05 per MB/s-hour
                assumptions.append(f"Provisioned throughput: {provisioned_throughput} MB/s × $0.05/MB/s-hour × 730 hours = ${throughput_cost:.2f}/month")
            
            total_monthly_cost = (monthly_storage_cost + throughput_cost) * resolved_count
            
            assumptions.append(f"EFS Performance Mode: {performance_mode}")
            assumptions.append(f"Storage: {storage_gb} GB × ${price_per_gb:.3f}/GB = ${monthly_storage_cost:.2f}/month")
            assumptions.append("Note: Actual costs depend on storage usage and throughput - this assumes minimal usage")
            
            return CostLineItem(
                cloud="aws",
                service="EFS",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"  # Low - storage usage varies significantly
            )
        
        # Special handling for ElastiCache
        if terraform_type in ["aws_elasticache_cluster", "aws_elasticache_replication_group"]:
            # ElastiCache pricing: node cost (based on instance type) + data transfer
            # We need instance type from size_hint
            instance_type_from_hint = size_hint.get("instance_type") or size_hint.get("node_type")
            
            if instance_type_from_hint:
                try:
                    # Try to get pricing - ElastiCache uses similar instance types to EC2
                    # Use EC2 pricing as approximation (ElastiCache pricing is typically similar)
                    hourly_price = None
                    if self.aws_bulk_client:
                        hourly_price = await self.aws_bulk_client.get_ec2_instance_price(
                            instance_type_from_hint,
                            resolved_region
                        )
                    elif self.aws_client:
                        hourly_price = await self.aws_client.get_ec2_instance_price(
                            instance_type_from_hint,
                            resolved_region
                        )
                    
                    if hourly_price:
                        node_count = resolved_count
                        monthly_cost = hourly_price * 730 * node_count
                        
                        assumptions.append(f"ElastiCache node type: {instance_type_from_hint}")
                        assumptions.append(f"Node count: {node_count}")
                        assumptions.append(f"Cost: {node_count} × ${hourly_price:.4f}/hour × 730 hours = ${monthly_cost:.2f}/month")
                        assumptions.append("Note: Using EC2 pricing as approximation - ElastiCache pricing may vary slightly")
                        assumptions.append("Note: Data transfer costs may apply for cross-AZ or internet traffic")
                        
                        return CostLineItem(
                            cloud="aws",
                            service="ElastiCache",
                            resource_name=resource_name,
                            terraform_type=terraform_type,
                            region=resolved_region,
                            monthly_cost_usd=monthly_cost,
                            pricing_unit="month",
                            assumptions=assumptions,
                            priced=True,
                            confidence="medium"
                        )
                except Exception as error:
                    logger.debug(f"Could not price ElastiCache for {resource_name}: {error}")
            
            # Fallback: estimate based on common cache node types
            assumptions.append("Note: ElastiCache cost = node cost (priced separately) + data transfer")
            assumptions.append("Common node types: cache.t3.micro (~$0.017/hour), cache.t3.small (~$0.034/hour)")
            assumptions.append("Actual cost depends on node type and count - check ElastiCache pricing for exact costs")
            
            return CostLineItem(
                cloud="aws",
                service="ElastiCache",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=0.0,  # Can't price without node type
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"
            )
        
        # Special handling for API Gateway
        if terraform_type == "aws_api_gateway_rest_api":
            # API Gateway pricing: free tier + requests
            # First 1M requests/month free, then $3.50 per 1M requests
            # Default assumption: minimal usage (within free tier)
            requests_per_month = usage.get("requests_per_month", 100000)  # Default 100K requests
            if requests_per_month == 0:
                requests_per_month = 100000
                assumptions.append("Assuming minimal API usage: 100,000 requests/month (within free tier)")
            
            # Free tier: first 1M requests/month
            free_tier_requests = 1000000
            billable_requests = max(0, requests_per_month - free_tier_requests)
            request_cost = (billable_requests / 1000000) * 3.50  # $3.50 per 1M requests
            
            total_monthly_cost = request_cost * resolved_count
            
            if requests_per_month <= free_tier_requests:
                assumptions.append(f"API Gateway requests: {requests_per_month:,} requests/month (within free tier - $0)")
                assumptions.append("Free tier: First 1M requests/month are free")
            else:
                assumptions.append(f"API Gateway requests: {requests_per_month:,} requests/month")
                assumptions.append(f"Billable requests: {billable_requests:,} × $3.50/1M = ${request_cost:.2f}/month")
            
            assumptions.append("Note: Additional costs for caching, custom domains, and data transfer may apply")
            
            return CostLineItem(
                cloud="aws",
                service="API Gateway",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"  # Low - request volume varies significantly
            )
        
        # Special handling for CloudFront
        if terraform_type == "aws_cloudfront_distribution":
            # CloudFront pricing: data transfer out + requests
            # Data transfer: ~$0.085/GB (first 10 TB), varies by region
            # Requests: ~$0.0075 per 10,000 HTTPS requests
            data_transfer_gb = usage.get("data_transfer_gb", 10.0)  # Default 10 GB
            if data_transfer_gb == 0:
                data_transfer_gb = 10.0
                assumptions.append("Assuming minimal data transfer: 10 GB/month (idle/light usage)")
            
            requests_per_month = usage.get("requests_per_month", 10000)  # Default 10K requests
            if requests_per_month == 0:
                requests_per_month = 10000
                assumptions.append("Assuming minimal requests: 10,000 requests/month")
            
            # Data transfer cost (first 10 TB tier)
            data_transfer_cost = data_transfer_gb * 0.085  # $0.085 per GB
            
            # Request cost (HTTPS requests)
            request_cost = (requests_per_month / 10000) * 0.0075  # $0.0075 per 10K requests
            
            total_monthly_cost = (data_transfer_cost + request_cost) * resolved_count
            
            assumptions.append(f"CloudFront data transfer: {data_transfer_gb} GB × $0.085/GB = ${data_transfer_cost:.2f}/month")
            assumptions.append(f"CloudFront requests: {requests_per_month:,} requests × $0.0075/10K = ${request_cost:.2f}/month")
            assumptions.append("Note: CloudFront pricing varies by region and data transfer volume - this assumes minimal usage")
            
            return CostLineItem(
                cloud="aws",
                service="CloudFront",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"  # Low - CDN usage varies greatly
            )
        
        # Special handling for Lambda
        if terraform_type == "aws_lambda_function":
            # Lambda pricing: free tier + invocations + compute time
            # First 1M requests/month free, then $0.20 per 1M requests
            # Compute: $0.0000166667 per GB-second (first 400K GB-seconds free)
            # Default assumption: minimal usage (within free tier)
            invocations_per_month = usage.get("invocations_per_month", 100000)  # Default 100K invocations
            if invocations_per_month == 0:
                invocations_per_month = 100000
                assumptions.append("Assuming minimal Lambda invocations: 100,000/month (within free tier)")
            
            memory_mb = size_hint.get("memory", 128)  # Default 128 MB
            duration_ms = usage.get("duration_ms", 100)  # Default 100ms
            duration_seconds = duration_ms / 1000.0
            
            # Free tier: 1M requests, 400K GB-seconds
            free_tier_requests = 1000000
            free_tier_gb_seconds = 400000
            
            billable_requests = max(0, invocations_per_month - free_tier_requests)
            request_cost = (billable_requests / 1000000) * 0.20  # $0.20 per 1M requests
            
            # Compute cost
            gb_seconds = invocations_per_month * (memory_mb / 1024.0) * duration_seconds
            billable_gb_seconds = max(0, gb_seconds - free_tier_gb_seconds)
            compute_cost = billable_gb_seconds * 0.0000166667  # Per GB-second
            
            total_monthly_cost = (request_cost + compute_cost) * resolved_count
            
            if invocations_per_month <= free_tier_requests and gb_seconds <= free_tier_gb_seconds:
                assumptions.append(f"Lambda invocations: {invocations_per_month:,}/month (within free tier - $0)")
                assumptions.append(f"Lambda compute: {gb_seconds:.0f} GB-seconds/month (within free tier - $0)")
                assumptions.append("Free tier: First 1M requests and 400K GB-seconds/month are free")
            else:
                assumptions.append(f"Lambda invocations: {invocations_per_month:,}/month")
                assumptions.append(f"Lambda compute: {gb_seconds:.0f} GB-seconds/month (memory: {memory_mb} MB, duration: {duration_ms}ms)")
                assumptions.append(f"Billable requests: {billable_requests:,} × $0.20/1M = ${request_cost:.2f}/month")
                assumptions.append(f"Billable compute: {billable_gb_seconds:.0f} GB-seconds × $0.0000166667 = ${compute_cost:.2f}/month")
            
            assumptions.append("Note: Actual Lambda costs depend heavily on invocation count and execution time")
            
            return CostLineItem(
                cloud="aws",
                service="Lambda",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"  # Low - Lambda costs vary greatly with usage
            )
        
        # Special handling for Transit Gateway
        if terraform_type == "aws_ec2_transit_gateway":
            # Transit Gateway pricing: ~$0.05/hour + data processing
            # Base cost: $0.05/hour * 730 hours/month = ~$36.50/month
            # Data processing: $0.02 per GB processed
            data_transfer_gb = usage.get("data_transfer_gb", 0)
            if data_transfer_gb == 0:
                data_transfer_gb = 1.0
                assumptions.append("Assuming minimal data transfer: 1 GB/month (idle/light usage)")
            
            hourly_cost = 0.05  # Base Transit Gateway hourly cost
            monthly_base = hourly_cost * 730  # ~$36.50/month
            data_processing_cost = data_transfer_gb * 0.02  # $0.02 per GB processed
            
            total_monthly_cost = (monthly_base + data_processing_cost) * resolved_count
            
            assumptions.append(f"Transit Gateway base cost: ${hourly_cost:.4f}/hour × 730 hours = ${monthly_base:.2f}/month")
            assumptions.append(f"Data processing: {data_transfer_gb} GB × $0.02/GB = ${data_processing_cost:.2f}")
            assumptions.append("Note: Actual costs depend on data transfer volume - this assumes minimal traffic")
            
            return CostLineItem(
                cloud="aws",
                service="VPC",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="medium"
            )
        
        # Special handling for ECS Fargate
        if terraform_type == "aws_ecs_service" and size_hint.get("launch_type") == "FARGATE":
            # Fargate pricing: vCPU + memory
            # vCPU: ~$0.04048 per vCPU-hour
            # Memory: ~$0.004445 per GB-hour
            # Default assumption: 0.25 vCPU, 0.5 GB (minimal task)
            vcpu = usage.get("vcpu", 0.25)
            memory_gb = usage.get("memory_gb", 0.5)
            if vcpu == 0:
                vcpu = 0.25
                assumptions.append("Assuming minimal vCPU: 0.25 vCPU (minimal task configuration)")
            if memory_gb == 0:
                memory_gb = 0.5
                assumptions.append("Assuming minimal memory: 0.5 GB (minimal task configuration)")
            
            task_count = resolved_count if resolved_count > 0 else 1
            hours_per_month = usage.get("hours_per_month", 730)  # Default 24/7
            
            vcpu_cost = vcpu * 0.04048 * hours_per_month * task_count
            memory_cost = memory_gb * 0.004445 * hours_per_month * task_count
            
            total_monthly_cost = vcpu_cost + memory_cost
            
            assumptions.append(f"Fargate task configuration: {vcpu} vCPU, {memory_gb} GB memory")
            assumptions.append(f"Task count: {task_count}")
            assumptions.append(f"vCPU cost: {vcpu} × $0.04048/vCPU-hour × {hours_per_month} hours × {task_count} tasks = ${vcpu_cost:.2f}/month")
            assumptions.append(f"Memory cost: {memory_gb} GB × $0.004445/GB-hour × {hours_per_month} hours × {task_count} tasks = ${memory_cost:.2f}/month")
            assumptions.append("Note: Actual costs depend on task count and runtime - this assumes minimal configuration")
            
            return CostLineItem(
                cloud="aws",
                service="ECS",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"  # Low - task count and runtime vary
            )
        
        # Special handling for SNS (Simple Notification Service)
        if terraform_type == "aws_sns_topic":
            # SNS pricing: free tier + messages
            # First 1M requests/month free, then $0.50 per 1M requests
            # Default assumption: minimal usage (within free tier)
            messages_per_month = usage.get("messages_per_month", 100000)  # Default 100K messages
            if messages_per_month == 0:
                messages_per_month = 100000
                assumptions.append("Assuming minimal SNS messages: 100,000/month (within free tier)")
            
            free_tier_messages = 1000000
            billable_messages = max(0, messages_per_month - free_tier_messages)
            message_cost = (billable_messages / 1000000) * 0.50  # $0.50 per 1M messages
            
            total_monthly_cost = message_cost * resolved_count
            
            if messages_per_month <= free_tier_messages:
                assumptions.append(f"SNS messages: {messages_per_month:,}/month (within free tier - $0)")
                assumptions.append("Free tier: First 1M messages/month are free")
            else:
                assumptions.append(f"SNS messages: {messages_per_month:,}/month")
                assumptions.append(f"Billable messages: {billable_messages:,} × $0.50/1M = ${message_cost:.2f}/month")
            
            assumptions.append("Note: Additional costs for SMS, email delivery, and data transfer may apply")
            
            return CostLineItem(
                cloud="aws",
                service="SNS",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"  # Low - message volume varies significantly
            )
        
        # Special handling for SQS (Simple Queue Service)
        if terraform_type == "aws_sqs_queue":
            # SQS pricing: free tier + requests
            # First 1M requests/month free, then $0.40 per 1M requests
            # Default assumption: minimal usage (within free tier)
            requests_per_month = usage.get("requests_per_month", 100000)  # Default 100K requests
            if requests_per_month == 0:
                requests_per_month = 100000
                assumptions.append("Assuming minimal SQS requests: 100,000/month (within free tier)")
            
            free_tier_requests = 1000000
            billable_requests = max(0, requests_per_month - free_tier_requests)
            request_cost = (billable_requests / 1000000) * 0.40  # $0.40 per 1M requests
            
            total_monthly_cost = request_cost * resolved_count
            
            if requests_per_month <= free_tier_requests:
                assumptions.append(f"SQS requests: {requests_per_month:,}/month (within free tier - $0)")
                assumptions.append("Free tier: First 1M requests/month are free")
            else:
                assumptions.append(f"SQS requests: {requests_per_month:,}/month")
                assumptions.append(f"Billable requests: {billable_requests:,} × $0.40/1M = ${request_cost:.2f}/month")
            
            assumptions.append("Note: Additional costs for data transfer and FIFO queues may apply")
            
            return CostLineItem(
                cloud="aws",
                service="SQS",
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=total_monthly_cost,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="low"  # Low - request volume varies significantly
            )
        
        # Extract instance type or SKU
        # For RDS, also check instance_class (common in Terraform)
        instance_type = (
            size_hint.get("instance_type") 
            or size_hint.get("instance_class")  # RDS uses instance_class
            or size_hint.get("sku")
        )
        
        # If no instance_type found, this resource type may not be supported for pricing
        # Return None to mark as unpriced (will be handled gracefully by caller)
        if not instance_type:
            # Log for debugging but don't raise error - some resources legitimately don't have instance types
            logger.debug(
                f"No instance_type/sku found for {resource_name} ({terraform_type}). "
                f"Service: {service}, Size hint: {size_hint}"
            )
            return None
        
        # Baseline fallback prices for common instance types (approximate).
        # These are used when real pricing APIs are unavailable so that local
        # demos still show non-zero costs.
        fallback_ec2_prices = {
            "t3.nano": 0.005,
            "t3.micro": 0.01,
            "t3.small": 0.02,
            "t3.medium": 0.04,
            "t3.large": 0.08,
        }
        fallback_rds_prices = {
            "db.t3.micro": 0.02,
            "db.t3.small": 0.04,
            "db.t3.medium": 0.08,
        }

        # Determine pricing unit and calculate
        hours_per_month = usage.get("hours_per_month", config.HOURS_PER_MONTH)
        assumptions.append(f"{hours_per_month} hours/month")

        def _fallback_hourly_price() -> Optional[float]:
            """Static demo prices used when official pricing is unavailable."""
            if "EC2" in service or terraform_type == "aws_instance":
                price = fallback_ec2_prices.get(instance_type)
                if price is not None:
                    assumptions.append(
                        f"Using static demo price for EC2 instance_type={instance_type}"
                    )
                return price
            if "RDS" in service or terraform_type.startswith("aws_db"):
                price = fallback_rds_prices.get(instance_type)
                if price is not None:
                    assumptions.append(
                        f"Using static demo price for RDS instance_class={instance_type}"
                    )
                return price
            return None
        
        try:
            hourly_price: Optional[float] = None
            
            # Route to appropriate pricing method if client is available
            # Prefer bulk pricing (fast, cached) over API client (slower, network-dependent)
            if self.aws_bulk_client is not None:
                if "EC2" in service or terraform_type == "aws_instance":
                    hourly_price = await self.aws_bulk_client.get_ec2_instance_price(
                        instance_type=instance_type,
                        region=resolved_region
                    )
                elif "RDS" in service or terraform_type.startswith("aws_db"):
                    # Extract engine from size_hint (e.g., {"engine": "mysql"}) or resource attributes
                    # Also check resource.get("size", {}) in case engine is stored there
                    engine = (
                        size_hint.get("engine") 
                        or resource.get("size", {}).get("engine")
                        or "mysql"  # Default to mysql
                    )
                    hourly_price = await self.aws_bulk_client.get_rds_instance_price(
                        instance_type=instance_type,
                        region=resolved_region,
                        engine=engine
                    )
            elif self.aws_client is not None:
                if "EC2" in service or terraform_type == "aws_instance":
                    hourly_price = await self.aws_client.get_ec2_instance_price(
                        instance_type=instance_type,
                        region=resolved_region
                    )
                elif "RDS" in service or terraform_type.startswith("aws_db"):
                    # Extract engine from size_hint (e.g., {"engine": "mysql"}) or resource attributes
                    # Also check resource.get("size", {}) in case engine is stored there
                    engine = (
                        size_hint.get("engine") 
                        or resource.get("size", {}).get("engine")
                        or "mysql"  # Default to mysql
                    )
                    hourly_price = await self.aws_client.get_rds_instance_price(
                        instance_type=instance_type,
                        region=resolved_region,
                        engine=engine
                    )

            # Fallback to static pricing if API client is missing or returned no price
            if hourly_price is None:
                hourly_price = _fallback_hourly_price()
            
            if hourly_price is None:
                return None
            
            # Calculate monthly cost
            monthly_cost = hourly_price * hours_per_month * resolved_count
            assumptions.append(f"${hourly_price:.4f}/hour × {resolved_count} instances")
            
            return CostLineItem(
                cloud="aws",
                service=service,
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=monthly_cost,
                pricing_unit="hour",
                assumptions=assumptions,
                priced=True,
                confidence=confidence
            )
        
        except AWSPricingError as error:
            logger.warning(f"Failed to price AWS resource {resource_name}: {error}")
            # Final fallback
            hourly_price = _fallback_hourly_price()
            if hourly_price is None:
                return None
            
            monthly_cost = hourly_price * hours_per_month * resolved_count
            assumptions.append(
                f"Fallback static price used after AWS pricing error: ${hourly_price:.4f}/hour × {resolved_count} instances"
            )
            
            return CostLineItem(
                cloud="aws",
                service=service,
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=monthly_cost,
                pricing_unit="hour",
                assumptions=assumptions,
                priced=True,
                confidence=confidence
            )
        except Exception as error:
            # Catch any unexpected errors during pricing
            logger.error(
                f"Unexpected error pricing AWS resource {resource_name} ({terraform_type}): {type(error).__name__}: {error}", 
                exc_info=True
            )
            hourly_price = _fallback_hourly_price()
            if hourly_price is None:
                return None

            monthly_cost = hourly_price * hours_per_month * resolved_count
            assumptions.append(
                f"Fallback static price used after unexpected error: ${hourly_price:.4f}/hour × {resolved_count} instances"
            )

            return CostLineItem(
                cloud="aws",
                service=service,
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=monthly_cost,
                pricing_unit="hour",
                assumptions=assumptions,
                priced=True,
                confidence=confidence
            )
    
    async def _price_azure_resource(
        self,
        resource: Dict[str, Any],
        resolved_region: str,
        resolved_count: int,
        assumptions: List[str]
    ) -> Optional[CostLineItem]:
        """
        Price an Azure resource.
        
        Args:
            resource: Resource from intent graph
            resolved_region: Resolved region
            resolved_count: Resolved resource count
            assumptions: List of assumptions (mutated)
        
        Returns:
            CostLineItem if priced, None otherwise
        """
        service = resource.get("service", "")
        terraform_type = resource.get("terraform_type", "")
        resource_name = resource.get("name", "unknown")
        size_hint = resource.get("size", {})
        usage = resource.get("usage", {})
        count_model = resource.get("count_model", {})
        confidence = count_model.get("confidence", "low")
        
        sku_name = size_hint.get("sku") or size_hint.get("instance_type")
        if not sku_name:
            return None
        
        hours_per_month = usage.get("hours_per_month", config.HOURS_PER_MONTH)
        assumptions.append(f"{hours_per_month} hours/month")
        
        try:
            hourly_price = await self.azure_client.get_virtual_machine_price(
                sku_name=sku_name,
                region=resolved_region
            )
            
            if hourly_price is None:
                return None
            
            monthly_cost = hourly_price * hours_per_month * resolved_count
            assumptions.append(f"${hourly_price:.4f}/hour × {resolved_count} instances")
            
            return CostLineItem(
                cloud="azure",
                service=service,
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=monthly_cost,
                pricing_unit="hour",
                assumptions=assumptions,
                priced=True,
                confidence=confidence
            )
        
        except AzurePricingError as error:
            logger.warning(f"Failed to price Azure resource {resource_name}: {error}")
            return None
    
    async def estimate(
        self,
        intent_graph: Dict[str, Any],
        region_override: Optional[str] = None,
        autoscaling_average_override: Optional[int] = None
    ) -> CostEstimate:
        """
        Estimate costs from intent graph.
        
        Args:
            intent_graph: Intent graph from Terraform interpreter
            region_override: Optional region override
            autoscaling_average_override: Optional autoscaling average override
        
        Returns:
            CostEstimate with line items and unpriced resources
        
        Raises:
            CostEstimatorError: If estimation fails
        """
        resources = intent_graph.get("resources", [])
        if not resources:
            raise CostEstimatorError("Intent graph has no resources")
        
        line_items: List[CostLineItem] = []
        unpriced_resources: List[UnpricedResource] = []
        
        for resource in resources:
            cloud = resource.get("cloud", "unknown")
            resource_name = resource.get("name", "unknown")
            terraform_type = resource.get("terraform_type", "unknown")
            region_info = resource.get("region", {})
            count_model = resource.get("count_model", {})
            
            # Resolve region
            resolved_region, region_assumptions = self._resolve_region(
                region_info,
                region_override
            )
            
            # Resolve count
            resolved_count, count_assumptions = self._resolve_count(
                count_model,
                autoscaling_average_override
            )
            
            if resolved_count is None:
                unpriced_resources.append(UnpricedResource(
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    reason="Cannot resolve resource count"
                ))
                continue
            
            # Collect assumptions
            assumptions = region_assumptions + count_assumptions
            
            # Price resource based on cloud provider
            line_item = None
            
            try:
                if cloud == "aws":
                    line_item = await self._price_aws_resource(
                        resource,
                        resolved_region,
                        resolved_count,
                        assumptions
                    )
                elif cloud == "azure":
                    line_item = await self._price_azure_resource(
                        resource,
                        resolved_region,
                        resolved_count,
                        assumptions
                    )
                elif cloud == "gcp":
                    # GCP pricing not fully implemented
                    unpriced_resources.append(UnpricedResource(
                        resource_name=resource_name,
                        terraform_type=terraform_type,
                        reason="GCP pricing not fully implemented"
                    ))
                    continue
                else:
                    unpriced_resources.append(UnpricedResource(
                        resource_name=resource_name,
                        terraform_type=terraform_type,
                        reason=f"Cloud provider '{cloud}' not supported for pricing"
                    ))
                    continue
            except (AWSPricingError, AzurePricingError, GCPPricingError) as error:
                # Expected pricing errors - mark as unpriced
                logger.warning(f"Pricing error for {resource_name} ({terraform_type}): {error}")
                unpriced_resources.append(UnpricedResource(
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    reason=f"Pricing lookup failed: {str(error)}"
                ))
                continue
            except Exception as error:
                # Unexpected errors during pricing - mark as unpriced rather than failing
                logger.error(f"Unexpected error pricing {resource_name} ({terraform_type}): {type(error).__name__}: {error}", 
                           exc_info=True)
                unpriced_resources.append(UnpricedResource(
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    reason="Unexpected error during pricing lookup"
                ))
                continue
            
            if line_item:
                line_items.append(line_item)
            else:
                unpriced_resources.append(UnpricedResource(
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    reason="Pricing not available for this resource type"
                ))
        
        # Calculate total
        total_monthly_cost = sum(item.monthly_cost_usd for item in line_items)
        
        # Use first priced resource's region, or default
        region = line_items[0].region if line_items else (region_override or "us-east-1")
        
        # Determine coverage status for each cloud provider
        coverage = self._calculate_coverage(resources, line_items, unpriced_resources)
        
        return CostEstimate(
            currency="USD",
            total_monthly_cost_usd=total_monthly_cost,
            line_items=line_items,
            unpriced_resources=unpriced_resources,
            region=region,
            pricing_timestamp=datetime.now(),
            coverage=coverage
        )
    
    def _calculate_coverage(
        self,
        resources: List[Dict[str, Any]],
        line_items: List[CostLineItem],
        unpriced_resources: List[UnpricedResource]
    ) -> Dict[str, str]:
        """
        Calculate coverage status for each cloud provider.
        
        Args:
            resources: All resources from intent graph
            line_items: Successfully priced resources
            unpriced_resources: Resources that couldn't be priced
        
        Returns:
            Dictionary mapping cloud provider to coverage status
        """
        coverage = {
            "aws": "full",  # AWS has comprehensive pricing support
            "azure": "not_supported_yet",  # Azure not yet supported
            "gcp": "not_supported_yet"
        }
        
        # Count resources by cloud
        cloud_resources: Dict[str, int] = {}
        cloud_priced: Dict[str, int] = {}
        
        for resource in resources:
            cloud = resource.get("cloud", "unknown")
            if cloud in ["aws", "azure", "gcp"]:
                cloud_resources[cloud] = cloud_resources.get(cloud, 0) + 1
        
        for item in line_items:
            cloud = item.cloud
            if cloud in ["aws", "azure", "gcp"]:
                cloud_priced[cloud] = cloud_priced.get(cloud, 0) + 1
        
        # Update coverage status
        for cloud in ["aws", "azure", "gcp"]:
            total = cloud_resources.get(cloud, 0)
            priced = cloud_priced.get(cloud, 0)
            
            if cloud == "gcp" or cloud == "azure":
                # Azure and GCP not yet supported
                coverage[cloud] = "not_supported_yet"
            elif cloud == "aws":
                # AWS always shows as "full" since we have comprehensive pricing support
                coverage[cloud] = "full"
            elif total == 0:
                # No resources for this cloud
                continue
            elif priced == total:
                coverage[cloud] = "full"
            elif priced > 0:
                coverage[cloud] = "partial"
            else:
                coverage[cloud] = "partial"  # Attempted but no prices found
        
        return coverage
    
    async def estimate_with_scenario(
        self,
        intent_graph: Dict[str, Any],
        scenario_input: ScenarioInput
    ) -> ScenarioEstimateResult:
        """
        Estimate costs with scenario modeling.
        
        Runs base estimate, then scenario estimate with overrides,
        and calculates deltas between them.
        
        Args:
            intent_graph: Intent graph from Terraform interpreter
            scenario_input: Scenario input parameters (overrides)
        
        Returns:
            ScenarioEstimateResult with base, scenario, and deltas
        
        Raises:
            CostEstimatorError: If estimation fails
        """
        # Run base estimate (existing logic)
        base_estimate = await self.estimate(
            intent_graph=intent_graph,
            region_override=None,
            autoscaling_average_override=None
        )
        
        # Build assumptions list
        assumptions = []
        
        # Run scenario estimate with overrides
        scenario_region_override = scenario_input.region_override
        scenario_autoscaling_override = scenario_input.autoscaling_average_override
        
        # Track if region changed
        region_changed = False
        if scenario_region_override and scenario_region_override != base_estimate.region:
            region_changed = True
            assumptions.append(
                f"Region overridden from {base_estimate.region} to {scenario_region_override}"
            )
        
        if scenario_autoscaling_override is not None:
            assumptions.append(
                f"Autoscaling average overridden to {scenario_autoscaling_override} instances"
            )
        
        if scenario_input.users is not None:
            assumptions.append(
                f"Users overridden to {scenario_input.users}"
            )
            # Note: User multiplier logic would be applied here for request-based services
            # Currently not implemented as per requirements
        
        # Run scenario estimate
        scenario_estimate = await self.estimate(
            intent_graph=intent_graph,
            region_override=scenario_region_override,
            autoscaling_average_override=scenario_autoscaling_override
        )
        
        # Calculate deltas
        deltas = self._calculate_deltas(
            base_estimate.line_items,
            scenario_estimate.line_items
        )
        
        return ScenarioEstimateResult(
            base_estimate=base_estimate,
            scenario_estimate=scenario_estimate,
            deltas=deltas,
            region_changed=region_changed,
            assumptions=assumptions
        )
    
    def _calculate_deltas(
        self,
        base_line_items: List[CostLineItem],
        scenario_line_items: List[CostLineItem]
    ) -> List[ScenarioDeltaLineItem]:
        """
        Calculate deltas between base and scenario line items.
        
        Matches resources by resource_name + terraform_type.
        If a resource exists in base but not scenario (unpriced), delta is null.
        If a resource exists in scenario but not base, it's included with base_cost = 0.
        
        Args:
            base_line_items: Base estimate line items
            scenario_line_items: Scenario estimate line items
        
        Returns:
            List of ScenarioDeltaLineItem
        """
        # Build lookup maps for efficient matching
        base_map = {
            (item.resource_name, item.terraform_type): item
            for item in base_line_items
        }
        scenario_map = {
            (item.resource_name, item.terraform_type): item
            for item in scenario_line_items
        }
        
        # Collect all unique resource keys
        all_keys = set(base_map.keys()) | set(scenario_map.keys())
        
        deltas = []
        
        for resource_key in all_keys:
            resource_name, terraform_type = resource_key
            base_item = base_map.get(resource_key)
            scenario_item = scenario_map.get(resource_key)
            
            # Skip if both are missing (shouldn't happen)
            if not base_item and not scenario_item:
                continue
            
            # Get costs (0 if missing)
            base_cost = base_item.monthly_cost_usd if base_item else 0.0
            scenario_cost = scenario_item.monthly_cost_usd if scenario_item else 0.0
            
            # Calculate delta
            delta_usd = scenario_cost - base_cost
            
            # Calculate delta percentage
            delta_percent = None
            if base_cost > 0:
                delta_percent = (delta_usd / base_cost) * 100
            
            deltas.append(ScenarioDeltaLineItem(
                resource_name=resource_name,
                terraform_type=terraform_type,
                base_monthly_cost_usd=base_cost,
                scenario_monthly_cost_usd=scenario_cost,
                delta_usd=delta_usd,
                delta_percent=delta_percent
            ))
        
        return deltas
