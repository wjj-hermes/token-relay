from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, ForeignKey, Index
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    balance = Column(Integer, default=0, nullable=False)  # token 余额
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    api_keys = relationship("ApiKey", back_populates="user", lazy="selectin")
    orders = relationship("Order", back_populates="user", lazy="selectin")
    subscriptions = relationship("Subscription", back_populates="user", lazy="selectin")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(50), default="default")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="api_keys")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), default="")  # 套餐介绍
    type = Column(String(20), nullable=False)  # quota / subscription
    price = Column(Integer, nullable=False)  # 价格，单位：分
    token_amount = Column(Integer, default=0)  # 额度包 token 数
    duration_days = Column(Integer, default=0)  # 订阅天数
    daily_limit = Column(Integer, default=0)  # 订阅每日上限，0=不限
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    order_no = Column(String(64), unique=True, nullable=False, index=True)
    amount = Column(Integer, nullable=False)  # 实付金额，单位：分
    status = Column(String(20), default="pending", nullable=False)  # pending/paid/failed/expired
    alipay_trade_no = Column(String(64), default="")
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="orders")
    product = relationship("Product", lazy="selectin")


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    model = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cost_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_usage_user_time", "user_id", "created_at"),)


class LLMModel(Base):
    __tablename__ = "llm_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)  # 显示名称
    model_id = Column(String(200), nullable=False)  # 上游模型 ID
    base_url = Column(String(500), nullable=False)  # API 地址
    api_key = Column(String(500), nullable=False)  # 密钥
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    start_at = Column(DateTime, nullable=False)
    expire_at = Column(DateTime, nullable=False)
    daily_limit = Column(Integer, default=0)  # 每日上限，0=不限
    daily_used = Column(Integer, default=0)
    last_reset_date = Column(Date, default=date.today)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="subscriptions")
