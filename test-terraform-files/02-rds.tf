# RDS Database Instance
resource "aws_db_instance" "main_db" {
  identifier     = "main-database"
  engine         = "mysql"
  engine_version = "8.0"
  instance_class = "db.t3.micro"
  allocated_storage = 20
  
  db_name  = "mydb"
  username = "admin"
  password = "changeme"
  
  skip_final_snapshot = true
}
