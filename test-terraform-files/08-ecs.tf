# ECS Cluster and Service
resource "aws_ecs_cluster" "main" {
  name = "main-cluster"
  
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  
  tags = {
    Name = "main-ecs-cluster"
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = "app-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  
  container_definitions = jsonencode([{
    name  = "app-container"
    image = "nginx:latest"
  }])
}
