from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String)
    balance = Column(Float, default=0.0)
    wallet = Column(String)
    
    # Feed purchase flags and timestamps
    toy1 = Column(Boolean, default=False)
    toy_time1 = Column(DateTime)
    toy2 = Column(Boolean, default=False)
    toy_time2 = Column(DateTime)
    toy3 = Column(Boolean, default=False)
    toy_time3 = Column(DateTime)
    toy4 = Column(Boolean, default=False)
    toy_time4 = Column(DateTime)
    toy5 = Column(Boolean, default=False)
    toy_time5 = Column(DateTime)
    toy6 = Column(Boolean, default=False)
    toy_time6 = Column(DateTime)

    toy7 = Column(Boolean, default=False)
    toy_time7 = Column(DateTime)
    toy8 = Column(Boolean, default=False)
    toy_time8 = Column(DateTime)
    toy9 = Column(Boolean, default=False)
    toy_time9 = Column(DateTime)
    toy10 = Column(Boolean, default=False)
    toy_time10 = Column(DateTime)
    toy11 = Column(Boolean, default=False)
    toy_time11 = Column(DateTime)

    total_spent_on_feed = Column(Float, default=0.0)  # Total spent on feed
    total_earned = Column(Float, default=0.0)  # Total earned
    total_bonus_profit = Column(Float, default=0.0)  # Total bonus profit
    total_withdrawals = Column(Float, default=0.0) 
    referred_by = Column(Integer, ForeignKey('users.id'))
    First_deposit = Column(Boolean, default=False)  # Add this line
    toy1_remaining_time = Column(Integer)  # Remaining time in seconds
    toy2_remaining_time = Column(Integer)
    toy3_remaining_time = Column(Integer)
    toy4_remaining_time = Column(Integer)
    toy5_remaining_time = Column(Integer)
    toy6_remaining_time = Column(Integer)

    toy7_remaining_time = Column(Integer)
    toy8_remaining_time = Column(Integer)
    toy9_remaining_time = Column(Integer)
    toy10_remaining_time = Column(Integer)
    toy11_remaining_time = Column(Integer)

    def __repr__(self):
        return f"<User(username='{self.username}', balance='{self.balance}')>"

class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    username = Column(String)
    wallet = Column(String)
    amount = Column(Float)
    withdrawal_time = Column(DateTime)
    status = Column(String, default="в обработке")

    user = relationship("User", backref="withdrawal_requests")  # Relationship

    def __repr__(self):
        return f"<WithdrawalRequest(user='{self.username}', amount='{self.amount}')>"