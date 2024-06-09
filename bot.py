import asyncio
import datetime
import pytz
import random
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import CallbackQuery
from sqlalchemy.sql.expression import or_
from sqlalchemy import func
from admin_panel import ADMIN_IDS, get_user_balance, get_user_withdrawals, top_up_balance, deduct_balance
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from admin_panel import get_pending_withdrawals
import payments
from db import Session, User
from models import WithdrawalRequest
from withdrawals import process_auto_withdrawal
from cryptobot_checks import delete_all_checks, delete_check, get_cryptobot_checks
from dataclasses import dataclass

storage = MemoryStorage()

# Replace with your actual bot token
API_TOKEN = ''
ADMIN_PANEL_CHAT_ID = ''
WITHDRAWAL_REQUESTS_CHAT_ID = '-'
ADMIN_LOG_CHAT_ID = "-"

CHANNEL_ID = -1002151662067  # ID вашего канала
CHANNEL_LINK = "https://t.me/sexy_cats"  # Ссылка на ваш канал


def generate_referral_link(user_id):
    return f"https://t.me/sexy_cat_bot?start={user_id}"


bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=storage)

# States for handling top-up amount input


class TopUpStates(StatesGroup):
    waiting_for_amount = State()


active_menus = {}
amounts = {}


@dataclass
class ReferralNotification:
    sender_id: int
    receiver_id: int


referral_notifications = []  # Список уведомлений о рефералах


async def check_channel_subscription(message: types.Message):
    chat_member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=message.from_user.id)
    if chat_member.status not in ("member", "creator", "administrator"):
        # Если пользователь не подписан, отправляем сообщение с inline-кнопками
        markup = InlineKeyboardMarkup(row_width=1)
        subscribe_button = InlineKeyboardButton(
            "Подписаться на канал", url=CHANNEL_LINK)
        markup.add(subscribe_button)
        await message.answer("Подпишитесь на наш канал, чтобы продолжить:\nПосле подписки на канал нажмите /start", reply_markup=markup)
        return False
    return True


@dp.message_handler(commands=['start'])
async def start_handler(message: types.Message):
    referral_id = message.get_args()
    session = Session()
    user = session.query(User).filter_by(id=message.from_user.id).first()
    referral_user = session.query(User).filter_by(id=referral_id).first()

    if not user:
        user = User(id=message.from_user.id,
                    username=message.from_user.username, referred_by=referral_id)
        session.add(user)
        session.commit()

        if referral_user:
            referral_notifications.append(ReferralNotification(
                sender_id=referral_user.id, receiver_id=user.id))
            await bot.send_message(referral_user.id, f"Ваш реферал @{user.username} присоединился!")
            await bot.send_message(ADMIN_LOG_CHAT_ID, f"Приглашение дрочера @{user.username} от @{referral_user.username}!")

    if not await check_channel_subscription(message):
        return

    if user.username:
        if "_" in user.username:
            username_display = "Дрочер"
        else:
            username_display = f"{user.username}"
    else:
        username_display = "Незнакомец"

    # Новый текст приветствия
    welcome_text = f"""Велком, {username_display} 👈🤓
Зашел посмотреть или все таки заработать TON?

Коротко о проекте:
Даешь кошке игрушку = ждешь оргазм = 💰

Чтобы начать, жми "Купить Игрушки🍌"!

Подпишись и присоединяйся к чату:
[Telegram Channel](https://t.me/sexy_cats)
[Telegram Chat](https://t.me/sexycats_chat)
"""

    # Путь к картинке
    image_path = "img/start.png"  # Предполагается, что start.jpg находится в папке img

    # Отправка сообщения с картинкой
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    item1 = types.KeyboardButton("💳Пополнить баланс")
    item2 = types.KeyboardButton("👛Кошелек")
    item3 = types.KeyboardButton("🐈Профиль")
    item4 = types.KeyboardButton("Купить Игрушки🍌")
    item5 = types.KeyboardButton("📥Вывести TON")
    item6 = types.KeyboardButton("🤝 Пригласить друга")
    markup.add(item1, item2, item3, item4, item5, item6)

    try:
        with open(image_path, 'rb') as photo:
            await message.answer_photo(photo, caption=welcome_text, parse_mode="Markdown", reply_markup=markup)
    except FileNotFoundError:
        print(f"Ошибка: Файл изображения не найден по пути {image_path}")
        # Отправить только текст
        await message.answer(welcome_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        await message.answer("Произошла ошибка при отправке приветственного сообщения.")

    active_menus[message.chat.id] = None
    session.close()


@dp.message_handler(lambda message: message.text == "💳Пополнить баланс")
async def handle_top_up(message: types.Message):
    await message.answer("Введите сумму пополнения в TON:")
    await TopUpStates.waiting_for_amount.set()


@dp.message_handler(state=TopUpStates.waiting_for_amount)
async def process_amount(message: types.Message, state: FSMContext):
    if message.text in ["👛Кошелек", "🐈Профиль", "Купить Игрушки🍌", "📥Вывести TON"]:
        # User wants to go to a different menu
        if message.text == "👛Кошелек":
            await handle_wallet(message)
        elif message.text == "🐈Профиль":
            await handle_profile(message)
        elif message.text == "Купить Игрушки🍌":
            await handle_buy_feed(message)
        elif message.text == "📥Вывести TON":
            await handle_withdrawal(message)
        await state.finish()
    else:
        # User is trying to enter an amount
        try:
            amount = float(message.text)
            if amount < 0.01:
                await message.answer("Минимальная сумма пополнения: 0.01 TON. Пожалуйста, введите сумму ещё раз:")
                return
            elif amount > 10000:
                await message.answer("Максимальная сумма пополнения: 10000 TON. Пожалуйста, введите сумму ещё раз:")
                return

            amounts[message.chat.id] = amount

            invoice = await payments.create_invoice(amount)

            markup = types.InlineKeyboardMarkup()
            pay_button = types.InlineKeyboardButton(
                "Оплатить счёт", url=invoice.bot_invoice_url)
            check_button = types.InlineKeyboardButton(
                "Проверить оплату", callback_data=f"check_{invoice.invoice_id}")
            markup.add(pay_button, check_button)

            await message.answer(f"Счёт на {amount} TON создан! После оплаты жми 👇", reply_markup=markup)
            await state.finish()

            # Check for first deposit and reward referrer
            session = Session()
            user = session.query(User).get(message.chat.id)

            if user.balance >= 2.0 and not user.First_deposit:
                user.First_deposit = True

                # Reward referrer
                if user.referred_by:
                    referrer = session.query(User).get(user.referred_by)
                    referrer.balance += 0.02
                    # Отправляем уведомление
                    await bot.send_message(referrer.id, f"Пришли деньги за дрочера 0.02")
                    session.commit()

            session.commit()
            session.close()

        except ValueError:
            await message.answer("Неверный формат суммы. Пожалуйста, введите число.")


@dp.callback_query_handler(lambda call: call.data.startswith('check_'))
async def handle_check_payment(call: types.CallbackQuery):
    invoice_id = call.data.split('_')[1]

    await call.message.answer("Проверяем статус счета... ⏳")

    # Добавляем задержку и повторную проверку статуса оплаты
    for _ in range(3):
        status = await payments.get_invoice_status(invoice_id)
        print(f"Статус оплаты для счета {invoice_id}: {status}")
        # Отправляем в ADMIN_LOG_CHAT_ID только если статус изменился
        if status != 'waiting':
            await bot.send_message(ADMIN_LOG_CHAT_ID, f"Статус оплаты для счета {invoice_id}: {status}")

        if status == 'paid':
            # Обработка оплаченного счета
            session = Session()
            user = session.query(User).get(call.message.chat.id)

            if call.message.chat.id in amounts:
                user.balance += amounts[call.message.chat.id]
                # Сумма пополнения
                deposited_amount = amounts[call.message.chat.id]
                del amounts[call.message.chat.id]

                # Проверка First_deposit и вознаграждение реферера (обновленная логика)
                if user.balance >= 2.0 and not user.First_deposit:
                    user.First_deposit = True

                    # Вознаграждение реферера
                    if user.referred_by:
                        referrer = session.query(User).get(user.referred_by)
                        referrer.balance += 0.02
                        # Уведомление
                        await bot.send_message(referrer.id, f"Пришли деньги за реферала 0.02")
                        session.commit()

                session.commit()
                session.close()
                print(
                    f"Счёт успешно оплачен! Баланс обновлен на {deposited_amount} TON. @{call.message.chat.username}")

                await bot.send_message(ADMIN_LOG_CHAT_ID, f"Счёт успешно оплачен! Баланс обновлен на {deposited_amount} TON. @{call.message.chat.username}")

                await call.message.answer(f"Счёт успешно оплачен! Баланс обновлен на {deposited_amount}.")
            else:
                print(
                    f"Не удалось найти сумму для пополнения. @{call.message.chat.username}")

                await bot.send_message(ADMIN_LOG_CHAT_ID, f"Не удалось найти сумму для пополнения. @{call.message.chat.username}")

                await call.message.answer("Не удалось найти сумму для пополнения.")

            break  # Выход из цикла, если счёт оплачен
        else:
            delay = random.randint(2, 5)
            await asyncio.sleep(delay)

    if status != 'paid':
        print(f"Счёт не оплачен. @{call.message.chat.username}")

        await bot.send_message(ADMIN_LOG_CHAT_ID, f"*Счёт не оплачен. @{call.message.chat.username}*")

        await call.message.answer("Счёт не оплачен. Повторите попытку позже.")


@dp.message_handler(lambda message: message.text == "👛Кошелек")
async def handle_wallet(message: types.Message):
    session = Session()
    user = session.query(User).get(message.chat.id)

    if not user:  # Check if user exists
        await message.answer("Пожалуйста, начните с команды /start")
        return

    image_path = "img/wallet.png"
    markup = types.InlineKeyboardMarkup()
    change_button = types.InlineKeyboardButton(
        "Изменить кошелёк", callback_data="change_wallet")
    markup.add(change_button)

    wallet_text = f"Ваш кошелёк: `{user.wallet}`" if user.wallet else "Дрочер, установи кошелек!"

    try:
        with open(image_path, 'rb') as photo:
            await message.answer_photo(photo, caption=wallet_text, parse_mode="Markdown", reply_markup=markup)
    except FileNotFoundError:
        print(f"Ошибка: Файл изображения не найден по пути {image_path}")
        # Отправить только текст
        await message.answer(wallet_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        await message.answer("Произошла ошибка при отправке информации о кошельке.")

    session.close()


@dp.callback_query_handler(lambda call: call.data == "change_wallet")
async def handle_change_wallet(call: types.CallbackQuery):
    markup = types.InlineKeyboardMarkup(row_width=1)
    enter_wallet_button = types.InlineKeyboardButton(
        "Ввести кошелёк", callback_data="enter_wallet")
    cryptobot_button = types.InlineKeyboardButton(
        "Установить вывод в CryptoBot", callback_data="set_cryptobot")
    markup.add(enter_wallet_button, cryptobot_button)

    await call.message.answer("Выберите способ установки кошелька:", reply_markup=markup)


@dp.callback_query_handler(lambda call: call.data == "enter_wallet")
async def handle_enter_wallet(call: types.CallbackQuery):
    await call.message.answer("Введите ваш новый TON кошелёк:")
    await dp.current_state().set_state("waiting_for_wallet")  # Set a temporary state


@dp.message_handler(state="waiting_for_wallet")
async def process_wallet(message: types.Message, state: FSMContext):
    main_menu_options = ["💳Пополнить баланс", "🐈Профиль",
                         "Купить Игрушки🍌", "👛Кошелек", "📥Вывести TON"]
    if message.text in main_menu_options:
        await state.finish()  # Exit the "waiting_for_wallet" state
        # Trigger the corresponding handler based on the message text
        if message.text == "💳Пополнить баланс":
            await handle_top_up(message)
        elif message.text == "🐈Профиль":
            await handle_profile(message)
        elif message.text == "Купить Игрушки🍌":
            await handle_buy_feed(message)
        elif message.text == "👛Кошелек":
            await handle_wallet(message)
        elif message.text == "📥Вывести TON":
            await handle_withdrawal(message)
    else:
        session = Session()
        user = session.query(User).get(message.chat.id)
        user.wallet = message.text
        session.commit()
        session.close()
        await message.answer("Ваш кошелёк сохранён!")
        await start_handler(message)
        await state.finish()


@dp.callback_query_handler(lambda call: call.data == "set_cryptobot")
async def handle_set_cryptobot(call: types.CallbackQuery):
    session = Session()
    user = session.query(User).get(call.message.chat.id)
    user.wallet = "@CryptoBot"  # Set wallet to "@CryptoBot"
    session.commit()
    session.close()
    await call.message.answer("Кошелек установлен - CryptoBot!")


@dp.message_handler(lambda message: message.text == "🐈Профиль")
async def handle_profile(message: types.Message):
    session = Session()
    user = session.query(User).get(message.chat.id)

    if not user:  # Check if user exists
        await message.answer("Пожалуйста, начните с команды /start")
        return

    user_level = get_user_level(user)

    # Проверяем наличие "_" в имени пользователя
    if user.username:
        if "_" in user.username:
            username_display = "Дрочер"
        else:
            username_display = f"{user.username}"
    else:
        username_display = "Незнакомец"

    profile_text = f"""
{username_display}
🏅 Ваш уровень: {user_level}  

🍌 Куплено игрушек: {user.total_spent_on_feed:.5f} TON 
💰 Заработано: {user.total_earned:.5f} TON
📈 Чистая прибыль: {user.total_bonus_profit:.5f} TON 
📤 Выведено: {user.total_withdrawals:.5f} TON

💎 TON баланс: {user.balance:.5f}
"""

    active_feed_text = ""
    for i in range(1, 12):
        toy_attr = f"toy{i}"
        time_attr = f"toy_time{i}"
        if getattr(user, toy_attr):
            purchase_time = getattr(user, time_attr)

            remaining_time_seconds = int(
                getattr(user, f"{toy_attr}_remaining_time"))

            if i == 1:
                amount = 0.1
                bonus = 0.085
            elif i == 2:
                amount = 0.5
                bonus = 0.07
            elif i == 3:
                amount = 1
                bonus = 0.45
            elif i == 4:
                amount = 3
                bonus = 0.85
            elif i == 5:
                amount = 2
                bonus = 0.65
            elif i == 6:
                amount = 5
                bonus = 1.10
#
            elif i == 7:
                amount = 8
                bonus = 1.40
            elif i == 8:
                amount = 10
                bonus = 2
            elif i == 9:
                amount = 15
                bonus = 3
            elif i == 10:
                amount = 20
                bonus = 3.5
            elif i == 11:
                amount = 25
                bonus = 4.40

            def get_hours_minutes_seconds_word(hours, minutes, seconds):
                if hours == 1:
                    hours_word = 'час'
                elif 2 <= hours <= 4:
                    hours_word = 'часа'
                else:
                    hours_word = 'часов'

                if minutes == 1:
                    minutes_word = 'минута'
                elif 2 <= minutes <= 4:
                    minutes_word = 'минуты'
                else:
                    minutes_word = 'минут'

                if seconds == 1:
                    seconds_word = 'секунда'
                else:
                    seconds_word = 'секунд'

                return hours_word, minutes_word, seconds_word

            hours_left = remaining_time_seconds // 3600
            minutes_left = (remaining_time_seconds % 3600) // 60
            seconds_left = remaining_time_seconds % 60
            hours_word, minutes_word, seconds_word = get_hours_minutes_seconds_word(
                hours_left, minutes_left, seconds_left)

            formatted_time = purchase_time.strftime("%d %b, %H:%M:%S")
            active_feed_text += f"🍌 {amount}+{bonus} TON от {formatted_time} (Осталось {hours_left} {hours_word} {minutes_left} {minutes_word} {seconds_left} {seconds_word})\n"
    if active_feed_text:
        profile_text += "\nИгрушки в работе!\n" + \
            active_feed_text + "\n*Время указано по UTC+0*"

    image_path = "img/profile.png"

    try:
        with open(image_path, 'rb') as photo:
            await message.answer_photo(photo, caption=profile_text, parse_mode="Markdown")
    except FileNotFoundError:
        print(f"Ошибка: Файл изображения не найден по пути {image_path}")
        await message.answer(profile_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        await message.answer("Произошла ошибка при отправке профиля.")
    session.close()


@dp.message_handler(lambda message: message.text == "Назад")
async def handle_back_to_main_menu(message: types.Message):
    await start_handler(message)


@dp.message_handler(lambda message: message.text == "Купить Игрушки🍌")
async def handle_buy_feed(message: types.Message):
    session = Session()
    user = session.query(User).get(message.chat.id)

    if not user:  # Check if user exists
        await message.answer("Пожалуйста, начните с команды /start")
        return

    # Check if any feed is available for purchase
    available_feed = None
    for i in range(1, 12):
        toy_attr = f"toy{i}"
        time_attr = f"toy_time{i}"
        if getattr(user, toy_attr) == 0:  # Feed not purchased
            available_feed = i
            break

    if not available_feed:
        await message.answer("Все игрушки уже у кошки, не мешай ей!")
        return
    image_path = "img/play.png"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # item1 = types.KeyboardButton("0.1 TON")
    item1 = types.KeyboardButton("8 TON")
    item2 = types.KeyboardButton("10 TON")
    item3 = types.KeyboardButton("15 TON")
    item4 = types.KeyboardButton("20 TON")
    item5 = types.KeyboardButton("25 TON")
    item6 = types.KeyboardButton("Назад")
    # markup.add(item1, item2, item3, item4)
    markup.add(item1, item2, item3, item4, item5)
    markup.row(item6)

    buy_feed_text = "😼Подарите возможность вашей кошке получить оргазм! \nКоторый она так любит…. \nВремя  оргазма занимает всего 16 часов."

    try:
        with open(image_path, 'rb') as photo:
            await message.answer_photo(photo, caption=buy_feed_text, parse_mode="Markdown", reply_markup=markup)
    except FileNotFoundError:
        print(f"Ошибка: Файл изображения не найден по пути {image_path}")
        # Отправить только текст
        await message.answer(buy_feed_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        await message.answer("Произошла ошибка при отправке сообщения о покупке игрушек.")
    session.close()


@dp.message_handler(lambda message: message.text == "🤝 Пригласить друга")
async def handle_referral_info(message: types.Message):
    session = Session()
    user = session.query(User).get(message.chat.id)

    if not user:  # Проверка на существование пользователя
        await message.answer("Пожалуйста, начните с команды /start")
        return

    referrals = session.query(User).filter_by(referred_by=user.id).all()
    active_referrals = [ref for ref in referrals if ref.First_deposit]
    referral_text = f"""
Мои дрочеры: {len(referrals)}
Дрочеры, сделавшие первое пополнение: {len(active_referrals)}

Уровни реферальных бонусов:

Уровень 1 (< 5 TON): Не начисляется процент с вывода дрочера
Уровень 2 (5-10 TON): 1% от каждого вывода
Уровень 3 (20-25 TON): 2% от каждого вывода
Уровень 4 (25+ TON): 3% от каждого вывода

Пополнение дрочера на 2.0 TON = 0.02 TON для вас!
"""

    referral_link = generate_referral_link(user.id)

    # Create inline keyboard with share button
    image_path = "img/referral.png"
    try:
        with open(image_path, 'rb') as photo:
            await message.answer_photo(photo, caption=referral_text + f"\nВаша реферальная ссылка: {referral_link}")
    except FileNotFoundError:
        print(f"Ошибка: Файл изображения не найден по пути {image_path}")
        # Отправить только текст
        await message.answer(referral_text + f"\nВаша реферальная ссылка: {referral_link}")
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        await message.answer("Произошла ошибка при отправке информации о рефералах.")

    session.close()  # Закрываем сессию после отправки сообщения


@dp.message_handler(lambda message: message.text == "Назад")
async def handle_back_to_profile(message: types.Message):
    await handle_profile(message)


@dp.message_handler(lambda message: message.text in ["8 TON", "10 TON", "15 TON", "20 TON", "25 TON"])
async def process_feed_purchase(message: types.Message):
    session = Session()
    user = session.query(User).get(message.chat.id)

    amount = float(message.text.split()[0])  # Extract amount
    if user.balance < amount:
        await message.answer("Недостаточно средств на балансе.")
        return

    # Determine the toy number (toy{i})
    if amount == 0.1:
        feed_number = 1
    elif amount == 0.5:
        feed_number = 2
    elif amount == 1:
        feed_number = 3
    elif amount == 3:
        feed_number = 4
    elif amount == 2:
        feed_number = 5
    elif amount == 5:
        feed_number = 6
        ##
    elif amount == 8:
        feed_number = 7
    elif amount == 10:
        feed_number = 8
    elif amount == 15:
        feed_number = 9
    elif amount == 20:
        feed_number = 10
    elif amount == 25:
        feed_number = 11

    # Check if the toy is already purchased
    toy_attr = f"toy{feed_number}"
    time_attr = f"toy_time{feed_number}"
    if getattr(user, toy_attr):
        await message.answer(f"Игрушка за {amount} TON уже куплена, жди пока она развлечется!")
        return

    # Purchase the toy
    user.balance -= amount
    setattr(user, toy_attr, True)

    # Updating time to Moscow time
    moscow_timezone = pytz.timezone('Europe/Moscow')
    moscow_time = datetime.datetime.now(moscow_timezone)
    setattr(user, time_attr, moscow_time)

    user.total_spent_on_feed += amount

    # Set the toy action time
    setattr(user, f"toy{feed_number}_remaining_time",
            86400)  # Changed time to 57600 seconds

    session.commit()
    session.close()

    # Calculate the return (with bonus)
    bonus = get_bonus_for_amount(amount)  # Use the new function
    return_amount = amount + bonus
    return_amount_rounded = round(return_amount, 2)

    await message.answer(f"Игрушка куплена! Жди пока малышка развлечется с ней! Вам вернется {return_amount_rounded} TON.")


async def check_toys_returns():
    while True:
        session = Session()
        users = session.query(User).filter(
            or_(
                User.toy1_remaining_time > 0,
                User.toy2_remaining_time > 0,
                User.toy3_remaining_time > 0,
                User.toy4_remaining_time > 0,
                User.toy5_remaining_time > 0,
                User.toy6_remaining_time > 0,

                User.toy7_remaining_time > 0,
                User.toy8_remaining_time > 0,
                User.toy9_remaining_time > 0,
                User.toy10_remaining_time > 0,
                User.toy11_remaining_time > 0,
            )
        ).all()

        for user in users:
            for i in range(1, 12):
                remaining_time_attr = f"toy{i}_remaining_time"
                remaining_time = getattr(user, remaining_time_attr)
                if remaining_time is not None and remaining_time > 0:
                    setattr(user, remaining_time_attr, remaining_time - 1)
                    if remaining_time == 1:
                        # Time's up, process the return
                        # Передаем номер игрушки (i)
                        await return_feed_amount(user.id, i, i)

        session.commit()
        session.close()
        await asyncio.sleep(1)  # Check every second


async def return_feed_amount(user_id, feed_number, _):
    session = Session()
    user = session.query(User).get(user_id)

    if feed_number == 1:
        amount = 0.1
    elif feed_number == 2:
        amount = 0.5
    elif feed_number == 3:
        amount = 1
    elif feed_number == 4:
        amount = 3
    elif feed_number == 5:
        amount = 2
    elif feed_number == 6:
        amount = 5
##
    elif feed_number == 7:
        amount = 8
    elif feed_number == 8:
        amount = 10
    elif feed_number == 9:
        amount = 15
    elif feed_number == 10:
        amount = 20
    elif feed_number == 11:
        amount = 25

    else:
        amount = 0  # Обработка ошибки, если номер игрушки некорректный

    bonus = get_bonus_for_amount(amount)
    return_amount = amount + bonus
    user.balance += return_amount

    setattr(user, f"toy{feed_number}", False)
    setattr(user, f"toy_time{feed_number}", None)
    setattr(user, f"toy{feed_number}_remaining_time", None)

    user.total_bonus_profit += bonus
    user.total_earned += return_amount

    await bot.send_message(ADMIN_LOG_CHAT_ID, f"У пользователя @{user.username} ({user_id}) произошел кошачий оргазм! Он получил {return_amount:.5f} TON")

    session.commit()
    session.close()

    # Introduce a 2-second delay before sending a message to the user
    await asyncio.sleep(5)
    await bot.send_message(user_id, f"Кошачий оргазм! Вы получили {return_amount:.5f} TON!")


def get_bonus_for_amount(amount):
    """Возвращает бонус для заданной суммы."""
    if amount == 0.1:
        return 0.085
    elif amount == 0.5:
        return 0.07
    elif amount == 1:
        return 0.45
    elif amount == 3:
        return 0.85
    elif amount == 2:
        return 0.65
    elif amount == 5:
        return 1.10
 #
    elif amount == 8:
        return 1.40
    elif amount == 10:
        return 2
    elif amount == 15:
        return 3
    elif amount == 20:
        return 3.5
    elif amount == 25:
        return 4.40

    else:
        return 0


# 📥Вывести TON

class WithdrawalStates(StatesGroup):
    waiting_for_amount = State()
    confirming_withdrawal = State()  # New state for confirmation


@dp.message_handler(lambda message: message.text == "📥Вывести TON")
async def handle_withdrawal(message: types.Message):
    session = Session()
    user = session.query(User).get(message.chat.id)

    if not user:  # Check if user exists
        await message.answer("Пожалуйста, начните с команды /start")
        return

    if not user.wallet:  # Check if wallet is set
        await message.answer("Эй дрочер, У тебя не установлен кошелек! Установите кошелек в разделе 👛Кошелек.")
        return

    # Get user level and calculate fee
    user_level = get_user_level(user)
    fee_percentage, _ = calculate_withdrawal_fee(
        1, user_level)  # Calculate for 1 TON to get percentage
    fee_percentage *= 100  # Convert to percentage

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Отменить вывод"))
    image_path = "img/withdraw.png"
    withdrawal_text = f"""
Ваш кошелек: `{user.wallet}`
Доступно к выводу: {user.balance:.5f} TON
Ваша комиссия: {fee_percentage:.1f}%
Введите сумму для Вывода (минимум 0.1 TON):
"""
    try:
        with open(image_path, 'rb') as photo:
            await message.answer_photo(photo, caption=withdrawal_text, parse_mode="Markdown", reply_markup=markup)
    except FileNotFoundError:
        print(f"Ошибка: Файл изображения не найден по пути {image_path}")
        # Отправить только текст
        await message.answer(withdrawal_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        await message.answer("Произошла ошибка при отправке сообщения о выводе.")

    await WithdrawalStates.waiting_for_amount.set()
    session.close()


@dp.message_handler(state=WithdrawalStates.waiting_for_amount)
async def process_withdrawal_amount(message: types.Message, state: FSMContext):
    if message.text == "Отменить вывод":
        await state.finish()  # Выходим из состояния ожидания суммы
        await start_handler(message)  # Возвращаемся в главное меню
        return

    session = Session()
    user = session.query(User).get(message.chat.id)

    try:
        amount = float(message.text)
        if amount < 0.1:
            await message.answer("Минимальная сумма для Вывода: 0.1 TON. Пожалуйста, введите сумму еще раз:")
            return

        # Определение уровня пользователя (для расчета комиссии)
        user_level = get_user_level(user)

        # Расчет комиссии и суммы к выплате (net_amount)
        fee, _ = calculate_withdrawal_fee(amount, user_level)
        net_amount = amount - fee

        if net_amount > user.balance:
            await message.answer("Недостаточно средств на балансе. Пожалуйста, введите сумму еще раз:")
            return

        # Сохранение текущего баланса перед выводом (для информации)
        current_balance = user.balance

        # Создание объекта запроса на вывод с суммой net_amount
        withdrawal_request = WithdrawalRequest(
            user_id=user.id,
            username=user.username,
            wallet=user.wallet,
            amount=net_amount,  # Используем сумму за вычетом комиссии
            withdrawal_time=datetime.datetime.utcnow(),
            status="в обработке"
        )
        session.add(withdrawal_request)
        session.commit()

        # Проверка, был ли присвоен ID запросу
        if withdrawal_request.id is None:
            raise ValueError("ID запроса на вывод не был присвоен!")

        withdrawal_request_id = withdrawal_request.id

        # Вычитаем сумму вывода из баланса пользователя
        user.balance -= amount
        user.total_withdrawals += amount

        # Формирование сообщения для канала админов с информацией о запросе
        withdrawal_message = f"""
🎖️ Заявка на Вывод 🎖️ 

Пользователь: @{user.username} ({user.id})
💎 TON баланс до вывода: {current_balance:.5f}
💎 TON баланс будет после вывода: {user.balance:.5f}
🍌 Куплено игрушек за все время: {user.total_spent_on_feed:.5f} TON 
💰 Заработано за все время пользователем: {user.total_earned:.5f} TON
📈 Чистая прибыль за все время: {user.total_bonus_profit:.5f} TON 
📤 Выведено: {user.total_withdrawals:.5f} TON

-----------------------------------
Сумма вывода: {amount} TON 
Комиссия: {fee:.3f} TON
Итого: {net_amount:.3f} TON
-----------------------------------

Кошелек: {user.wallet}

"""

        # Генерация сообщения с кнопками для подтверждения/отмены
        confirmation_message, confirmation_markup = generate_confirmation_message(
            withdrawal_request_id, withdrawal_message)
        await bot.send_message(WITHDRAWAL_REQUESTS_CHAT_ID, confirmation_message, reply_markup=confirmation_markup)

        # Информирование пользователя о сумме к выплате и комиссии
        await message.answer(f"Поставлено на Вывод {net_amount:.3f} TON (комиссия {fee:.3f} TON).")
        await start_handler(message)  # Возвращение в главное меню

        await state.finish()  # Выход из состояния ожидания суммы

    except ValueError:
        await message.answer("Неверный формат суммы. Пожалуйста, введите число.")

    session.commit()
    session.close()


# функция для генерации сообщения с кнопками
def generate_confirmation_message(withdrawal_request_id, withdrawal_message):
    markup = types.InlineKeyboardMarkup()
    cancel_button = types.InlineKeyboardButton(
        "Отменить", callback_data=f"cancel_{withdrawal_request_id}")
    confirm_button = types.InlineKeyboardButton(
        "Подтвердить", callback_data=f"confirm_{withdrawal_request_id}")
    auto_withdraw_button = types.InlineKeyboardButton(
        "Авто вывод", callback_data=f"auto_withdraw_{withdrawal_request_id}")  # Новая кнопка

    # операторы для отладки (необязательно)
    print(
        f"Generated cancel button callback data: {cancel_button.callback_data}")
    print(
        f"Generated confirm button callback data: {confirm_button.callback_data}")
    print(
        f"Generated auto withdraw button callback data: {auto_withdraw_button.callback_data}")

    # Добавляем кнопку в разметку
    markup.add(cancel_button, confirm_button, auto_withdraw_button)
    return withdrawal_message, markup


@dp.callback_query_handler(lambda call: call.data.startswith('cancel_'))
async def handle_cancel_withdrawal(call: CallbackQuery):
    withdrawal_request_id = int(call.data.split('_')[1])
    session = Session()
    withdrawal_request = session.query(
        WithdrawalRequest).get(withdrawal_request_id)

    if withdrawal_request and withdrawal_request.status == "в обработке":
        user = session.query(User).get(withdrawal_request.user_id)
        user.balance += withdrawal_request.amount
        # Корректируем total_withdrawals
        user.total_withdrawals -= withdrawal_request.amount
        withdrawal_request.status = "отменено"
        session.commit()
        await call.message.answer(f"Заявка {withdrawal_request.id} отменена. У пользователя @{user.username} неверно указан кошелек или другие проблемы.")
        await bot.send_message(user.id, f"Вывод на {withdrawal_request.amount} TON отменен, средства возвращены на ваш баланс. Возможно у вас неправильно указан кошелек.")
    else:
        await call.answer("Невозможно отменить вывод.")
    session.close()


@dp.callback_query_handler(lambda call: call.data.startswith('cancel_'))
async def handle_cancel_withdrawal(call: CallbackQuery):
    try:
        # Извлекаем ID запроса на вывод
        withdrawal_request_id = int(call.data.split('_')[1])

        session = Session()
        # Получаем объект запроса на вывод из базы данных
        withdrawal_request = session.query(
            WithdrawalRequest).get(withdrawal_request_id)

        # Проверяем, существует ли запрос и находится ли он в обработке
        if withdrawal_request and withdrawal_request.status == "в обработке":
            # Получаем пользователя, связанного с запросом
            user = session.query(User).get(withdrawal_request.user_id)

            # Возвращаем сумму на баланс пользователя
            user.balance += withdrawal_request.amount
            # Корректируем общее количество выводов
            user.total_withdrawals -= withdrawal_request.amount

            # Изменяем статус запроса на "отменено"
            withdrawal_request.status = "отменено"
            session.commit()

            # Отправляем сообщения пользователю и в чат
            await call.message.answer("Ах, вывод отменен! Слыш дрочер, ты что одной рукой писал кошелек? А где другая, а??")
            await bot.send_message(user.id, "Вывод отменен, средства возвращены на ваш баланс.")
        else:
            await call.answer("Невозможно отменить вывод.")

        session.close()
    except Exception as e:
        # Обработка любых исключений
        await call.answer(f"Ошибка при обработке запроса: {e}")
        # (Опционально) Логирование ошибки для дальнейшего анализа


@dp.callback_query_handler(lambda call: call.data.startswith('confirm_'))
async def handle_confirm_withdrawal(call: CallbackQuery):
    try:
        withdrawal_request_id = int(call.data.split('_')[1])
        session = Session()
        withdrawal_request = session.query(
            WithdrawalRequest).get(withdrawal_request_id)

        if withdrawal_request and withdrawal_request.status == "в обработке":
            user = session.query(User).get(withdrawal_request.user_id)

            # Изменяем статус запроса на "выполнено"
            withdrawal_request.status = "выполнено"
            session.commit()

            # Начисление бонуса рефереру при подтверждении
            if user.referred_by:
                referrer = session.query(User).get(user.referred_by)
                _, referrer_bonus = calculate_withdrawal_fee(
                    withdrawal_request.amount, get_user_level(user))
                referrer.balance += referrer_bonus
                session.commit()

                # Отправка уведомления рефереру с уровнем реферала
                await notify_referrer(referrer.id, referrer_bonus, user.username, get_user_level(user))

            # Отправляем сообщения пользователю и в чат
            await call.message.answer(f"Заявка {withdrawal_request.id} подтверждена. Вывод на {withdrawal_request.amount:.3f} TON для пользователя @{user.username} выполнен.")
            await bot.send_message(user.id, f"Твои {withdrawal_request.amount:.3f} TON уже в кошельке! Жду тебя снова, дрочер!")
        else:
            await call.answer("Невозможно подтвердить вывод.")

        session.close()
    except Exception as e:
        # Обработка любых исключений
        await call.answer(f"Ошибка при обработке запроса: {e}")


async def notify_referrer(referrer_id, amount, referred_username, referred_user_level):
    if referred_user_level > 1:  # Отправляем уведомление только если уровень больше 1
        await bot.send_message(
            referrer_id,
            f"💰 Вам начислен бонус {amount:.5f} TON за вывод средств кого-то из ваших друзей."
        )


async def send_message(chat_id, message):
    await bot.send_message(chat_id, message)


@dp.callback_query_handler(lambda call: call.data.startswith('auto_withdraw_'))
async def handle_auto_withdrawal(call: CallbackQuery):
    from withdrawals import process_auto_withdrawal

    try:
        withdrawal_request_id = int(call.data.split('_')[2])
        session = Session()
        withdrawal_request = session.query(
            WithdrawalRequest).get(withdrawal_request_id)

        if withdrawal_request and withdrawal_request.status == "в обработке":
            user = session.query(User).get(withdrawal_request.user_id)

            # Запускаем автоматический вывод
            await process_auto_withdrawal(
                withdrawal_request_id,
                user.id,
                withdrawal_request.amount,
                withdrawal_request.wallet,
                send_message  # Передаем функцию send_message
            )

            await call.message.answer(f"Заявка {withdrawal_request.id} обработана автоматически. Вывод для пользователя @{user.username} запущен.")
        else:
            await call.answer("Невозможно выполнить автоматический вывод.")

        session.close()
    except Exception as e:
        await call.answer(f"Ошибка при обработке запроса: {e}")


def calculate_withdrawal_fee(amount):
    return amount * 0.05
# КОМИССИЯИ УРОВНИ


def get_user_level(user):
    total_spent = user.total_spent_on_feed
    if total_spent < 5:
        return 1
    elif total_spent < 10:
        return 2
    elif total_spent < 20:
        return 3
    elif total_spent < 25:
        return 4
    else:
        return 4


def calculate_withdrawal_fee(amount, user_level):
    if user_level == 1:
        return amount * 0.10, 0  # 10% комиссия, 0% рефереру
    elif user_level == 2:
        return amount * 0.09, amount * 0.01  # 9% комиссия, 1% рефереру
    elif user_level == 3:
        return amount * 0.08, amount * 0.02  # 8% комиссия, 2% рефереру
    else:  # user_level == 4
        return amount * 0.07, amount * 0.03  # 7% комиссия, 3% рефереру


# ADMIN PANEL

# Состояния для обработки команд администратора
class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_action = State()
    waiting_for_amount = State()
    selecting_withdrawal = State()
    # Новое состояние для ввода текста рассылки
    waiting_for_broadcast_text = State()
    confirming_broadcast = State()  # Состояние для подтверждения рассылки
    # Новое состояние для выбора метода ввода пользователя
    selecting_user_method = State()


USERS_PER_PAGE = 5   # Количество пользователей, отображаемых на странице


async def get_users_page(page_num):
    session = Session()
    offset = (page_num - 1) * USERS_PER_PAGE
    users = session.query(User).order_by(User.id).offset(
        offset).limit(USERS_PER_PAGE).all()
    session.close()
    return users


@dp.message_handler(commands=['admin'], user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_admin_command(message: types.Message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🏆 Top Referrers"),
        types.KeyboardButton("📥 Выбрать заявку")
    )
    markup.add(
        types.KeyboardButton("👤 Выбрать пользователя"),
        types.KeyboardButton("Чеки CryptoBot")
    )
    markup.add(
        types.KeyboardButton("📢 Рассылка"),
        types.KeyboardButton("💰 Заработок")  # Добавляем кнопку "Заработок"
    )
    await message.answer("Выберите действие:", reply_markup=markup)


@dp.message_handler(lambda message: message.text == "💰 Заработок", user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_earnings_command(message: types.Message):
    session = Session()
    total_earned = session.query(func.sum(WithdrawalRequest.amount)).filter_by(
        status="выполнено").scalar() or 0
    session.close()

    # Calculate earnings with a 10% commission deduction
    commission = total_earned * 0.10
    final_earnings = total_earned - commission

    await message.answer(f"Заработано: {total_earned:.5f} TON\nЗаработок после комиссии (10%): {final_earnings:.5f} TON")


@dp.message_handler(lambda message: message.text == "📢 Рассылка", user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_broadcast_command(message: types.Message):
    await message.answer("Введите текст рассылки:")
    await AdminStates.waiting_for_broadcast_text.set()

# Обработчик ввода текста рассылки


@dp.message_handler(state=AdminStates.waiting_for_broadcast_text, user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_broadcast_text(message: types.Message, state: FSMContext):
    broadcast_text = message.text

    # Создаем клавиатуру с кнопками "Да" и "Нет"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "Да", callback_data="confirm_broadcast"))
    markup.add(types.InlineKeyboardButton(
        "Нет", callback_data="cancel_broadcast"))

    await message.answer(f"Вы уверены, что хотите разослать сообщение:\n\n{broadcast_text}\n\n", reply_markup=markup)
    # Сохранение текста в state
    await state.update_data(broadcast_text=broadcast_text)
    await AdminStates.confirming_broadcast.set()

# Обработчик нажатия на кнопку "Да"


@dp.callback_query_handler(lambda call: call.data == "confirm_broadcast", state=AdminStates.confirming_broadcast, user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def confirm_broadcast(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    broadcast_text = data.get("broadcast_text")
    await state.finish()

    session = Session()
    users = session.query(User).all()
    session.close()

    await call.message.answer("Рассылка началась...")

    # Цикл рассылки по всем пользователям
    for user in users:
        try:
            await bot.send_message(user.id, broadcast_text)
            # Задержка для избежания ограничения API Telegram
            await asyncio.sleep(2)
        except Exception as e:
            await call.message.answer(f"Ошибка при отправке сообщения пользователю @{user.username}: {e}")
            # Задержка для избежания ограничения API Telegram
            await asyncio.sleep(2)
    await call.message.answer("Рассылка завершена.")

# Обработчик нажатия на кнопку "Нет"


@dp.callback_query_handler(lambda call: call.data == "cancel_broadcast", state=AdminStates.confirming_broadcast, user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def cancel_broadcast(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await call.message.answer("Рассылка отменена.")


@dp.message_handler(lambda message: message.text == "Чеки CryptoBot", user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_cryptobot_checks(message: types.Message):
    checks_info = await get_cryptobot_checks()

    if checks_info:
        # Создаем клавиатуру с кнопками для удаления
        keyboard = types.InlineKeyboardMarkup()
        for line in checks_info.splitlines():
            check_id = line.split(",")[0].split(":")[1].strip()
            keyboard.add(types.InlineKeyboardButton(
                text=f"Удалить {check_id}", callback_data=f"delete_check_{check_id}"))
        keyboard.add(types.InlineKeyboardButton(
            text="Удалить все", callback_data="delete_all_checks"))

        await message.answer(f"Чеки CryptoBot:\n{checks_info}", reply_markup=keyboard)

    else:
        await message.answer("Не удалось получить информацию о чеках.")

# Обработчик нажатия на кнопку "Удалить"


@dp.callback_query_handler(lambda c: c.data.startswith('delete_check_'))
async def delete_check_handler(callback_query: types.CallbackQuery):
    check_id = int(callback_query.data.split('_')[-1])
    deleted_check = await delete_check(check_id)

    if deleted_check:
        await bot.answer_callback_query(callback_query.id, text=f"Чек {check_id} успешно удален")
        # Обновляем информацию о чеках после удаления
        await handle_cryptobot_checks(callback_query.message)
    else:
        await bot.answer_callback_query(callback_query.id, text=f"Ошибка при удалении чека {check_id}")

# Обработчик нажатия на кнопку "Удалить все"


@dp.callback_query_handler(lambda c: c.data == "delete_all_checks")
async def delete_all_checks_handler(callback_query: types.CallbackQuery):
    await delete_all_checks()
    await bot.answer_callback_query(callback_query.id, text="Все чеки успешно удалены")
    # Обновляем информацию о чеках после удаления
    await handle_cryptobot_checks(callback_query.message)


@dp.message_handler(lambda message: message.text == "📥 Выбрать заявку", user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_select_withdrawal(message: types.Message, state: FSMContext):
    pending_withdrawals = get_pending_withdrawals()

    if not pending_withdrawals:
        await message.answer("Нет заявок на вывод в обработке.")
        return

    markup = types.InlineKeyboardMarkup()
    for withdrawal in pending_withdrawals:
        button_text = f"{withdrawal.username} - {withdrawal.amount} TON"
        callback_data = f"withdrawal_id_{withdrawal.id}"
        markup.add(types.InlineKeyboardButton(
            button_text, callback_data=callback_data))

    await message.answer("Выберите заявку на вывод:", reply_markup=markup)


@dp.callback_query_handler(lambda call: call.data.startswith('withdrawal_id_'))
async def handle_withdrawal_selection(call: CallbackQuery):
    withdrawal_id = int(call.data.split('_')[2])
    session = Session()
    withdrawal_request = session.query(WithdrawalRequest).get(withdrawal_id)

    if withdrawal_request:
        user = session.query(User).get(withdrawal_request.user_id)
        # Предположим, что вы хотите показать текущий баланс.
        current_balance = user.balance

        withdrawal_message = f"""
🎖️ Заявка на Вывод 🎖️ 

Пользователь: @{user.username} ({user.id})
💎 TON баланс до вывода: {current_balance:.5f}
💎 TON баланс будет после вывода: {user.balance - withdrawal_request.amount:.5f}
🍌 Куплено игрушек за все время: {user.total_spent_on_feed:.5f} TON 
💰 Заработано за все время пользователем: {user.total_earned:.5f} TON
📈 Чистая прибыль за все время: {user.total_bonus_profit:.5f} TON 
📤 Выведено: {user.total_withdrawals + withdrawal_request.amount:.5f} TON

Сумма вывода: {withdrawal_request.amount} TON
Кошелек: {withdrawal_request.wallet}



"""

        # сообщение о подтверждении и разметку
        confirmation_message, confirmation_markup = generate_confirmation_message(
            withdrawal_request.id, withdrawal_message
        )

        # сообщение в приватный чат
        await bot.send_message(WITHDRAWAL_REQUESTS_CHAT_ID, confirmation_message, reply_markup=confirmation_markup)
        await call.answer("Заявка отправлена в чат для обработки.")
    else:
        await call.answer("Заявка не найдена.")

    session.close()


@dp.message_handler(lambda message: message.text == "👤 Выбрать пользователя", user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_select_user(message: types.Message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "UserName", callback_data="select_by_username"))
    markup.add(types.InlineKeyboardButton(
        "ID", callback_data="select_by_id"))  # Добавляем кнопку "ID"
    markup.add(types.InlineKeyboardButton(
        "Список", callback_data="select_from_list"))
    await message.answer("Выберите способ выбора пользователя:", reply_markup=markup)
    await AdminStates.selecting_user_method.set()


@dp.callback_query_handler(lambda call: call.data == "select_by_username", state=AdminStates.selecting_user_method, user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_select_by_username(call: CallbackQuery):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Назад"))
    # Отправляем сообщение с markup
    await call.message.answer("Введите @username пользователя: (или нажмите 'Назад' для отмены)", reply_markup=markup)
    await AdminStates.waiting_for_user_id.set()


@dp.callback_query_handler(lambda call: call.data == "select_by_id", state=AdminStates.selecting_user_method, user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_select_by_id(call: CallbackQuery):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Назад"))
    await call.message.answer("Введите ID пользователя: (или нажмите 'Назад' для отмены)", reply_markup=markup)
    await AdminStates.waiting_for_user_id.set()
    await dp.current_state().set_state("waiting_for_user_id")


@dp.message_handler(state="waiting_for_user_id", user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def process_user_id(message: types.Message, state: FSMContext):
    if message.text == 'Назад':
        await state.finish()
        await handle_admin_command(message)
        return

    try:
        user_id = int(message.text)
        session = Session()
        user = session.query(User).get(user_id)
        session.close()

        if user:
            await state.update_data(user_id=user.id)

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add(types.KeyboardButton("Баланс"),
                       types.KeyboardButton("Выплаты"))
            markup.add(types.KeyboardButton("Пополнить"),
                       types.KeyboardButton("Списать"))
            markup.add(types.KeyboardButton("Статистика"), types.KeyboardButton(
                "Убрать меню"))  # Добавляем кнопку "Статистика"

            await message.answer(f"Выбран пользователь: @{user.username}\nВыберите действие:", reply_markup=markup)
            await AdminStates.waiting_for_action.set()
        else:
            await message.answer("Пользователь не найден.")

    except ValueError:
        await message.answer("Неверный формат ID. Пожалуйста, введите число.")

# Обработчик нажатия на кнопку "Список"


@dp.callback_query_handler(lambda call: call.data == "select_from_list", state=AdminStates.selecting_user_method, user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_select_from_list(call: CallbackQuery):
    users = await get_users_page(1)
    await display_users_page(call.message, users, 1)


async def display_users_page(message, users, page_num):
    markup = InlineKeyboardMarkup(row_width=2)
    for user in users:
        button = InlineKeyboardButton(
            f"@{user.username}", callback_data=f"user_id_{user.id}")
        markup.insert(button)

    if page_num > 1:
        prev_button = InlineKeyboardButton(
            "⬅️", callback_data=f"prev_page_{page_num-1}")
        markup.row(prev_button)

    if len(users) == USERS_PER_PAGE:
        next_button = InlineKeyboardButton(
            "➡️", callback_data=f"next_page_{page_num+1}")
        markup.row(next_button)

    await message.answer("Выберите Username пользователя:", reply_markup=markup)


@dp.message_handler(state=AdminStates.waiting_for_user_id, user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def process_user_id(message: types.Message, state: FSMContext):
    if message.text == 'Назад':
        await state.finish()
        await handle_admin_command(message)
        return

    username = message.text.lstrip('@')  # Удаление "@" из введенного текста

    session = Session()
    user = session.query(User).filter_by(username=username).first()
    session.close()

    if user:
        await state.update_data(user_id=user.id)

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("Баланс"),
                   types.KeyboardButton("Выплаты"))
        markup.add(types.KeyboardButton("Пополнить"),
                   types.KeyboardButton("Списать"))
        markup.add(types.KeyboardButton("Статистика"), types.KeyboardButton(
            "Убрать меню"))  # Добавляем кнопку "Статистика"

        await message.answer(f"Выбран пользователь: @{user.username}\nВыберите действие:", reply_markup=markup)
        await AdminStates.waiting_for_action.set()
    else:
        await message.answer("Пользователь не найден.")


@dp.callback_query_handler(lambda call: call.data.startswith('user_id_'), state=AdminStates.selecting_user_method, user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def handle_user_selection(call: CallbackQuery, state: FSMContext):
    user_id = int(call.data.split('_')[2])
    await state.update_data(user_id=user_id)

    session = Session()
    user = session.query(User).get(user_id)
    session.close()
    new_chat_id = -
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Баланс"), types.KeyboardButton("Выплаты"))
    markup.add(types.KeyboardButton("Пополнить"),
               types.KeyboardButton("Списать"))
    markup.add(types.KeyboardButton("Убрать меню"))

    await call.message.answer(f"Выбран пользователь: @{user.username}\nВыберите действие:", reply_markup=markup)
    await AdminStates.waiting_for_action.set()


@dp.callback_query_handler(lambda call: call.data.startswith('prev_page_'))
async def handle_prev_page(call: types.CallbackQuery):
    page_num = int(call.data.split('_')[2])
    users = await get_users_page(page_num)
    await display_users_page(call.message, users, page_num)


@dp.callback_query_handler(lambda call: call.data.startswith('next_page_'))
async def handle_next_page(call: types.CallbackQuery):
    page_num = int(call.data.split('_')[2])
    users = await get_users_page(page_num)
    await display_users_page(call.message, users, page_num)


@dp.message_handler(state=AdminStates.waiting_for_action, user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def process_action(message: types.Message, state: FSMContext):
    action = message.text.lower()
    data = await state.get_data()
    user_id = data.get("user_id")

    if action == "/admin":  # Check for /admin command
        await state.finish()
        await handle_admin_command(message)
        return

    elif action == "баланс":
        balance = get_user_balance(user_id)
        if balance is not None:
            await message.answer(f"Баланс пользователя: {balance:.5f} TON")
        else:
            await message.answer("Пользователь не найден.")
    elif action == "выплаты":
        withdrawals = get_user_withdrawals(user_id)
        if withdrawals:
            withdrawals_text = "\n".join(
                [f"{w.id} - {w.amount} TON ({w.status})" for w in withdrawals])
            await message.answer(f"Выплаты пользователя:\n{withdrawals_text}")
        else:
            await message.answer(f"У пользователя нет выплат.")
    elif action == "пополнить":
        await message.answer("Введите сумму для пополнения:")
        await AdminStates.waiting_for_amount.set()
        await state.update_data(action="пополнить")
    elif action == "списать":
        await message.answer("Введите сумму для списания:")
        await AdminStates.waiting_for_amount.set()
        await state.update_data(action="списать")
    elif action == "убрать меню":
        await state.finish()
        await handle_admin_command(message)
    elif action == "статистика":  # Обработка команды "Статистика"
        # Вызываем функцию для показа статистики
        await show_user_stats(message, user_id)
    else:
        await message.answer("Неизвестное действие.")

# ... (your existing code)


async def show_user_stats(message: types.Message, user_id: int):
    session = Session()
    user = session.query(User).get(user_id)
    session.close()

    if not user:
        await message.answer("Пользователь не найден.")
        return

    user_level = get_user_level(user)

    stats_text = f"""
Статистика пользователя @{user.username} ({user.id}):

🏅 Уровень: {user_level}
💎 Баланс: {user.balance:.5f} TON

🍌 Куплено игрушек: {user.total_spent_on_feed:.5f} TON 
💰 Заработано: {user.total_earned:.5f} TON
📈 Чистая прибыль: {user.total_bonus_profit:.5f} TON 
📤 Выведено: {user.total_withdrawals:.5f} TON

"""

    active_feed_text = ""
    for i in range(1, 13):
        toy_attr = f"toy{i}"
        time_attr = f"toy_time{i}"
        if getattr(user, toy_attr):
            purchase_time = getattr(user, time_attr)

            remaining_time_seconds = int(
                getattr(user, f"{toy_attr}_remaining_time"))

            if i == 1:
                amount = 0.1
                bonus = 0.085
            elif i == 2:
                amount = 0.5
                bonus = 0.07
            elif i == 3:
                amount = 1
                bonus = 0.45
            elif i == 4:
                amount = 3
                bonus = 0.85
            elif i == 5:
                amount = 2
                bonus = 0.65
            elif i == 6:
                amount = 5
                bonus = 1.10
##
            elif i == 7:
                amount = 8
                bonus = 1.40
            elif i == 8:
                amount = 10
                bonus = 2
            elif i == 9:
                amount = 15
                bonus = 3
            elif i == 10:
                amount = 20
                bonus = 3.5
            elif i == 11:
                amount = 25
                bonus = 4.40

            def get_hours_minutes_seconds_word(hours, minutes, seconds):
                if hours == 1:
                    hours_word = 'час'
                elif 2 <= hours <= 4:
                    hours_word = 'часа'
                else:
                    hours_word = 'часов'

                if minutes == 1:
                    minutes_word = 'минута'
                elif 2 <= minutes <= 4:
                    minutes_word = 'минуты'
                else:
                    minutes_word = 'минут'

                if seconds == 1:
                    seconds_word = 'секунда'
                else:
                    seconds_word = 'секунд'

                return hours_word, minutes_word, seconds_word

            hours_left = remaining_time_seconds // 3600
            minutes_left = (remaining_time_seconds % 3600) // 60
            seconds_left = remaining_time_seconds % 60
            hours_word, minutes_word, seconds_word = get_hours_minutes_seconds_word(
                hours_left, minutes_left, seconds_left)

            formatted_time = purchase_time.strftime("%d %b, %H:%M:%S")
            active_feed_text += f"🍌 {amount}+{bonus} TON от {formatted_time} (Осталось {hours_left} {hours_word} {minutes_left} {minutes_word} {seconds_left} {seconds_word})\n"
    if active_feed_text:
        stats_text += "\nИгрушки в работе:\n" + active_feed_text + ""

    # Убираем клавиатуру
    await message.answer(stats_text, reply_markup=types.ReplyKeyboardRemove())

# Handler for amount input


@dp.message_handler(state=AdminStates.waiting_for_amount, user_id=ADMIN_IDS, chat_id=ADMIN_PANEL_CHAT_ID)
async def process_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        data = await state.get_data()
        user_id = data.get("user_id")
        action = data.get("action")

        if action == "пополнить":
            success = top_up_balance(user_id, amount)
            if success:
                await message.answer(f"Баланс пользователя пополнен на {amount:.5f} TON.")
            else:
                await message.answer("Ошибка пополнения баланса.")
        elif action == "списать":
            success = deduct_balance(user_id, amount)
            if success:
                await message.answer(f"С баланса пользователя списано {amount:.5f} TON.")
            else:
                await message.answer("Ошибка списания с баланса.")

        await state.finish()
        await handle_admin_command(message)
    except ValueError:
        await message.answer("Неверный format суммы. Пожалуйста, введите число.")


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(check_toys_returns())  # Start the background task
    executor.start_polling(dp, skip_updates=True)
