# Terraform Test Files

This folder contains multiple Terraform files to test different AWS resource types and verify pricing works correctly.

## Files:

1. **01-ec2.tf** - EC2 instance (t3.micro)
2. **02-rds.tf** - RDS MySQL database (db.t3.micro)
3. **03-s3.tf** - S3 bucket with versioning
4. **04-vpc.tf** - VPC, subnets, internet gateway, security groups (free resources)
5. **05-lambda.tf** - Lambda function with IAM role
6. **06-alb.tf** - Application Load Balancer
7. **07-ebs.tf** - EBS volume (gp3, 100GB)
8. **08-ecs.tf** - ECS cluster and Fargate task definition
9. **09-cloudfront.tf** - CloudFront distribution
10. **10-elasticache.tf** - ElastiCache Redis cluster

## Usage:

You can upload this entire folder or select individual files to test pricing for different AWS services.

## Expected Results:

- **EC2**: Should be priced (t3.micro instance)
- **RDS**: Should be priced (db.t3.micro MySQL)
- **S3**: Should be priced (minimal cost for basic bucket)
- **VPC/Networking**: Should show $0.00 (free resources)
- **Lambda**: May need pricing support added
- **ALB**: May need pricing support added
- **EBS**: May need pricing support added
- **ECS**: May need pricing support added
- **CloudFront**: May need pricing support added
- **ElastiCache**: May need pricing support added
