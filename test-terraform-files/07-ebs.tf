# EBS Volume
resource "aws_ebs_volume" "data_volume" {
  availability_zone = "ap-south-1a"
  size              = 100
  type              = "gp3"
  
  tags = {
    Name = "data-volume"
  }
}

resource "aws_volume_attachment" "data_volume_attachment" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data_volume.id
  instance_id = aws_instance.web_server.id
}
