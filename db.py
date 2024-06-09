import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, WithdrawalRequest

engine = create_engine("sqlite:///bot_data.db")  # Replace with your desired database URL
Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)

def get_user(user_id):
    session = Session()
    user = session.query(User).filter_by(id=user_id).first()
    session.close()
    return user

def create_user(user_id, username, referred_by=None):
    session = Session()
    user = User(id=user_id, username=username, referred_by=referred_by)
    session.add(user)
    session.commit()
    session.close()
    return user

def update_user_wallet(user_id, wallet):
    session = Session()
    user = session.query(User).filter_by(id=user_id).first()
    user.wallet = wallet
    session.commit()
    session.close()

def update_user_balance(user_id, amount):
    session = Session()
    user = session.query(User).filter_by(id=user_id).first()
    user.balance += amount
    session.commit()
    session.close()

def create_withdrawal_request(user_id, username, wallet, amount):
    session = Session()
    withdrawal_request = WithdrawalRequest(
        user_id=user_id,
        username=username,
        wallet=wallet,
        amount=amount,
        withdrawal_time=datetime.datetime.utcnow()  # Store withdrawal time
    )
    session.add(withdrawal_request)
    session.commit()
    session.close()
    return withdrawal_request