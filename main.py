from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from google.cloud import vision
from openai import AsyncOpenAI
import configparser
import logging
import os
from datetime import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize configparser
config = configparser.ConfigParser()
config.read('config.ini')

# Retrieve keys and tokens from config files
OPENAI_API_KEY = config['Keys']['OPENAI_API_KEY']
TELEGRAM_TOKEN = config['Keys']['TELEGRAM_TOKEN']
GOOGLE_APPLICATION_CREDENTIALS = config['Keys']['GOOGLE_APPLICATION_CREDENTIALS']

# Set the environment variable for Google Cloud authentication
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS

# Initialize the OpenAI client
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Initialize the Google Cloud Vision client
vision_client = vision.ImageAnnotatorClient()

# Your Telegram bot token
TOKEN = TELEGRAM_TOKEN
BOT_USERNAME = '@NomNomNutriBot'

# In-memory storage for user meals (use a database in a real application)
user_meals = {}

# Define states
TRACKING, CONFIRMING_DELETE, CONFIRMING_SAVE = range(3)


# Commands
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Hello! I am NomNom NutriBot. I can help you track your nutrition. '
        'Type /help to see the list of commands.'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'List of commands:\n'
        '/start - Start the bot\n'
        '/help - Show this message\n'
        '/track - Track your meal\n'
        '/view - View your meal history\n'
        '/delete - Delete your meal history\n'
        '/cancel - Cancel the current operation'
    )


async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('What did you eat? Please describe your meal or upload an image.')
    return TRACKING


async def view_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat.id
    meals = user_meals.get(user_id, [])
    if not meals:
        await update.message.reply_text('You have not tracked any meals yet.')
    else:
        meal_history = "\n\n".join([f"Timestamp: {meal['timestamp']}\n\n{meal['response']}" for meal in meals])
        await update.message.reply_text('Your meal history:\n\n' + meal_history)


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat.id
    if user_id in user_meals and user_meals[user_id]:
        await update.message.reply_text('Are you sure you want to delete your meal history? Type "yes" to confirm.')
        return CONFIRMING_DELETE
    else:
        await update.message.reply_text('You have no meal history to delete.')
        return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Operation cancelled.')
    return ConversationHandler.END


async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat.id
    if update.message.text.lower() == 'yes':
        user_meals[user_id] = []
        await update.message.reply_text('Your meal history has been deleted.')
    else:
        await update.message.reply_text('Delete operation cancelled.')
    return ConversationHandler.END


async def handle_track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat.id
    text: str = update.message.text
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Provide nutritional advice using OpenAI
    try:
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful nutrition assistant."},
                {"role": "user", "content": f"I ate {text}. Please provide nutritional advice including estimated calories."}
            ]
        )
        advice = response.choices[0].message.content.strip()

        # Store the generated advice and timestamp in context to use later
        context.user_data['response'] = advice
        context.user_data['timestamp'] = timestamp

        await update.message.reply_text(advice)
        await update.message.reply_text('Would you like to save this meal? (yes/no)')
        return CONFIRMING_SAVE
    except Exception as e:
        logger.error(f"Error from OpenAI API: {str(e)}")
        await update.message.reply_text('Meal tracked, but unable to fetch nutritional advice at the moment.')
        return ConversationHandler.END


async def confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat.id
    user_response = update.message.text.lower()

    if user_response == 'yes':
        if user_id not in user_meals:
            user_meals[user_id] = []
        user_meals[user_id].append({
            "response": context.user_data['response'],
            "timestamp": context.user_data['timestamp']
        })
        await update.message.reply_text('Meal saved successfully.')
    else:
        await update.message.reply_text('Meal not saved.')

    return ConversationHandler.END


async def handle_response(text: str) -> str:
    processed: str = text.lower()

    if 'hello' in processed:
        return 'Hello There!'

    if 'how are you' in processed:
        try:
            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "How are you?"}
                ]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Error from OpenAI API: {str(e)}")
            return "I am fine, thank you!"  # Default response if OpenAI fails

    if 'bye' in processed:
        return 'Goodbye!'

    return 'I do not understand that command'


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text: str = update.message.text
    response: str = await handle_response(text)
    await update.message.reply_text(response)


async def analyze_food_image(image_path: bytes) -> str:
    try:
        image = vision.Image(content=bytes(image_path))
        response = vision_client.label_detection(image=image)
        labels = response.label_annotations

        # Define a list of common food items including Singaporean dishes
        common_food_items = [
            "apple", "banana", "orange", "pizza", "burger", "sandwich", "salad", "pasta", "bread", "cake", "cookie",
            "chocolate", "ice cream", "fish", "meat", "chicken", "beef", "pork", "egg", "cheese", "milk", "yogurt",
            "rice", "sushi", "noodles", "soup", "potato", "fries", "vegetable", "fruit", "chicken rice", "durian",
            "laksa", "char kway teow", "hainanese chicken rice", "roti prata", "chilli crab", "satay", "nasi lemak",
            "hokkien mee", "bak kut teh", "kaya toast", "mee goreng", "rojak", "popiah"
        ]

        # Extract food-related labels
        food_items = [label.description for label in labels if label.description.lower() in common_food_items]

        if not food_items:
            return "No recognizable food items found in the image."

        food_list = ", ".join(food_items)

        # Use GPT-3.5 to generate nutritional advice including estimated calories based on detected items
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful nutrition assistant."},
                {"role": "user", "content": f"I ate {food_list}. Please provide nutritional advice including estimated calories."}
            ]
        )
        advice = response.choices[0].message.content.strip()
        return food_list, advice
    except Exception as e:
        logger.error(f"Error from Google Cloud Vision or OpenAI API: {str(e)}")
        return "", "Unable to analyze the image at the moment."


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat.id
    photo = update.message.photo[-1]
    file = await photo.get_file()
    file_path = await file.download_as_bytearray()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        # Analyze the image and provide nutritional information
        food_list, analysis = await analyze_food_image(file_path)

        # Store the generated advice and timestamp in context to use later
        context.user_data['response'] = analysis
        context.user_data['timestamp'] = timestamp

        await update.message.reply_text(analysis)
        await update.message.reply_text('Would you like to save this meal? (yes/no)')
        return CONFIRMING_SAVE
    except Exception as e:
        logger.error(f"Error analyzing image: {str(e)}")
        await update.message.reply_text('Failed to analyze the image.')
        return ConversationHandler.END


async def error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f'Update {update} caused error {context.error}')


if __name__ == '__main__':
    logger.info('Starting Bot...')
    app = Application.builder().token(TOKEN).build()

    # Conversation handler for tracking meals
    track_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler('track', track_command)],
        states={
            TRACKING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_track),
                MessageHandler(filters.PHOTO, handle_image)
            ],
            CONFIRMING_SAVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_save)]
        },
        fallbacks=[CommandHandler('cancel', cancel_command)]
    )

    # Conversation handler for deleting meals
    delete_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler('delete', delete_command)],
        states={
            CONFIRMING_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete)],
        },
        fallbacks=[CommandHandler('cancel', cancel_command)]
    )

    # Commands
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('view', view_command))
    app.add_handler(track_conversation_handler)
    app.add_handler(delete_conversation_handler)
    app.add_handler(CommandHandler('cancel', cancel_command))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Error
    app.add_error_handler(error)

    # Polls the bot
    app.run_polling(poll_interval=1)
