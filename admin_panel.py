# admin_panel.py
from db import Session, User, WithdrawalRequest

# Replace with your actual admin IDs
ADMIN_IDS = [5433758555, 1256945123]  # Replace with actual admin IDs

# Function to get user balance
def get_user_balance(user_id):
    session = Session()
    user = session.query(User).get(user_id)
    session.close()
    if user:
        return user.balance 
    else:
        return None

# Function to get user withdrawals
def get_user_withdrawals(user_id):
    session = Session()
    withdrawals = session.query(WithdrawalRequest).filter_by(user_id=user_id).all()
    session.close()
    return withdrawals

def get_pending_withdrawals():
    session = Session()
    pending_withdrawals = session.query(WithdrawalRequest).filter_by(status="в обработке").all()
    session.close()
    return pending_withdrawals

# Function to top-up user balance
def top_up_balance(user_id, amount):
    session = Session()
    user = session.query(User).get(user_id)
    if user:
        user.balance += amount
        session.commit()
        session.close()
        return True 
    else:
        session.close()
        return False

# Function to deduct from user balance
def deduct_balance(user_id, amount):
    session = Session()
    user = session.query(User).get(user_id)
    if user and user.balance >= amount:
        user.balance -= amount
        session.commit()
        session.close()
        return True
    else:
        session.close()
        return False
    

    