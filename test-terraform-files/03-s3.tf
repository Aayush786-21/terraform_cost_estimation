# S3 Bucket
resource "aws_s3_bucket" "data_storage" {
  bucket = "my-data-storage-bucket-12345"
  
  tags = {
    Name        = "Data Storage"
    Environment = "Production"
  }
}

resource "aws_s3_bucket_versioning" "data_storage_versioning" {
  bucket = aws_s3_bucket.data_storage.id
  
  versioning_configuration {
    status = "Enabled"
  }
}
