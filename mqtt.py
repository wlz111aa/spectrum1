# 该文件包含各类可被Kali敏感信息检测工具识别的泄露内容
# 1. MQTT 密码（重点匹配你关注的 MQTT_PASSWORD）
MQTT_PASSWORD = "MqttSecretPass123!"
MQTT_BROKER_URL = "mqtts://admin:MQTT@123456@mqtt.example.com:8883"
mosquitto_password = "Mosquitto@7890"
emqx_auth_pwd = "EMQX!Pass6789"

# 2. API 密钥/令牌
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyzABCDE"
JWT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"

# 3. 数据库/系统密码
DB_PASSWORD = "MySQL@Pass123456"
SSH_PRIVATE_KEY = """
-----BEGIN RSA PRIVATE KEY-----
MIICXQIBAAKBgQDQENQujkLfZfc5Tu9Z1L28hUa8Kh0J4lRE0hPy1X3Xrt7j7gK+
WZ890Jg760z+6U9wQ7y6J1gR8jv+8H1a28j3g4h5k6l7m8n9b0v1c2x3d4f5g6h7j
8k9l0p1q2w3e4r5t6y7u8i9o0p1a2s3d4f5g6h7j8k9l0z1x2c3v4b5n6m7l8k9j0
1k2l3m4n5b6v7c8x9z0a1s2d3f4g5h6j7k8l9p0o1i2u3y4t5r6e7w8q9p0a1s2d3
f4g5h6j7k8l9z0x1c2v3b4n5m6l7k8j9i0o1p2l3m4n5b6v7c8x9z0a1s2d3f4g5h
6j7k8l9p0o1i2u3y4t5r6e7w8q9p0a1s2d3f4g5h6j7k8l9z0x1c2v3b4n5m6l7k8
j9i0o1p2l3m4n5b6v7c8x9z0a1s2d3f4g5h6j7k8l9p0o1i2u3y4t5r6e7w8q9p0=
-----END RSA PRIVATE KEY-----
"""
ROOT_PASSWORD = "Root@123456789"

# 4. 其他敏感凭证

TWILIO_AUTH_TOKEN = "1234567890abcdefghijklmnopqrstuvwxyz"
