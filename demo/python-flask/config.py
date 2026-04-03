import os


class Config:
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")

    DATABASE_URL = os.getenv(
        "DATABASE_URL", "postgresql://app:secret@localhost:5432/orders"
    )
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

    PAYMENT_GATEWAY_URL = os.getenv(
        "PAYMENT_GATEWAY_URL", "https://api.payments.example.com"
    )
    PAYMENT_GATEWAY_TIMEOUT = int(os.getenv("PAYMENT_GATEWAY_TIMEOUT", "5"))

    INVENTORY_SERVICE_URL = os.getenv(
        "INVENTORY_SERVICE_URL", "http://inventory-svc:8081"
    )
