import pandas as pd
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters
)
import asyncio # Import asyncio for managing the event loop
import nest_asyncio # Import nest_asyncio for handling nested event loops

# ----------- خواندن فایل اکسل --------------
# Read the excel file without any header to handle complex header structures manually
df_temp = pd.read_excel("tabdil.xlsx", header=None)

# Assuming the first row (index 0) of the loaded data contains the actual headers,
# and the first column of that row is empty/NaN, we extract headers from the second column onwards.
# For example, df_temp.iloc[0] might be [NaN, 'UTS', 'HV', 'HB', 'HRC', 'HRB', ...]
actual_headers = [str(col) for col in df_temp.iloc[0, 1:].tolist()]

# Create the main DataFrame by skipping the header row and the first (empty/index) column
df = df_temp.iloc[1:, 1:].copy()
df.columns = actual_headers # Assign the extracted headers

# Convert all relevant columns to numeric, coercing errors to NaN
for col in df.columns:
    df[col] = pd.to_numeric(df[col], errors='coerce')

# Interpolate for better accuracy, now that columns are numeric
df_interp = df.interpolate(method="linear")


# ------------- استیت‌ها ---------------------
SELECT_MODE, SELECT_TYPE, ENTER_VALUE = range(3)

# Global variable to hold the bot application instance
_telegram_bot_app = None

# ------------- شروع ربات ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [InlineKeyboardButton("🔄 تبدیل انواع سختی", callback_data="convert_hardness")],
        [InlineKeyboardButton("📈 سختی → استحکام کششی", callback_data="hardness_strength")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "سلام! 👋\nچکاری می‌تونم برات انجام بدم؟",
        reply_markup=reply_markup
    )

    return SELECT_MODE


# ---------------- انتخاب حالت -----------------
async def select_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mode = query.data
    context.user_data["mode"] = mode

    if mode == "convert_hardness":
        await query.edit_message_text("نوع تبدیل را وارد کنید (مثال: HRC to HV)")
        return SELECT_TYPE

    if mode == "hardness_strength":
        await query.edit_message_text("نوع سختی را وارد کنید (مثال: HB to UTS)")
        return SELECT_TYPE


# ---------------- انتخاب نوع تبدیل -----------------
async def select_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["convert_type"] = update.message.text.strip()
    await update.message.reply_text("لطفاً مقدار سختی را وارد کنید:")
    return ENTER_VALUE


# ---------------- محاسبه تبدیل -----------------
async def convert_value(update: Update, context: ContextTypes.DEFAULT_TYPE):

    value = float(update.message.text)
    convert_type = context.user_data["convert_type"]

    # فرض: ستون‌های فایل اکسل برابر نام سختی‌هاست، مثال: HRC - HV - HB
    input_unit, output_unit = convert_type.split(" to ")

    if input_unit not in df.columns or output_unit not in df.columns:
        await update.message.reply_text("واحد وارد شده در فایل اکسل موجود نیست!")
        return ConversationHandler.END

    # Select only the relevant columns for interpolation
    interp_data = df_interp[[input_unit, output_unit]].copy()

    # Drop rows where either input_unit or output_unit is NaN to ensure valid data points for interpolation
    interp_data.dropna(subset=[input_unit, output_unit], inplace=True)

    if interp_data.empty:
        await update.message.reply_text(f"خطا در محاسبه تبدیل. داده کافی (زوج‌های {input_unit} و {output_unit} معتبر) برای اینترپولیشن/اکسترپولیشن در فایل اکسل موجود نیست.")
        return ConversationHandler.END

    if
len(interp_data) < 2:
        await update.message.reply_text(f"خطا در محاسبه تبدیل. حداقل دو نقطه داده معتبر (زوج‌های {input_unit} و {output_unit} بدون NaN) برای انجام اینترپولیشن/اکسترپولیشن خطی نیاز است.")
        return ConversationHandler.END

    # Store original min/max for extrapolation check
    min_orig_input = interp_data[input_unit].min()
    max_orig_input = interp_data[input_unit].max()
    is_extrapolation = False
    if pd.notna(min_orig_input) and pd.notna(max_orig_input):
        if value < min_orig_input or value > max_orig_input:
            is_extrapolation = True

    # Add the value to be interpolated as a new row with pd.NA for the output unit
    new_row = pd.DataFrame({input_unit: [value], output_unit: [pd.NA]})
    interp_data = pd.concat([interp_data, new_row], ignore_index=True)

    # Sort by the input unit to prepare for linear interpolation
    interp_data = interp_data.sort_values(by=input_unit).reset_index(drop=True)

    # Ensure the output_unit column is numeric before interpolation to avoid FutureWarning
    interp_data[output_unit] = pd.to_numeric(interp_data[output_unit], errors='coerce')

    # Perform linear interpolation on the output_unit column
    # Use limit_direction='both' to ensure extrapolation is attempted if needed
    interp_data[output_unit] = interp_data[output_unit].interpolate(method='linear', limit_direction='both')

    # Find the interpolated result for the input value
    # Filter for the row where input_unit is equal to value and get the output_unit
    result_row = interp_data[interp_data[input_unit] == value]

    if result_row.empty:
        await update.message.reply_text(f"خطا در محاسبه تبدیل. مقدار {input_unit} = {value} در مجموعه داده پس از اینترپولیشن یافت نشد. ممکن است خطایی در پردازش داده رخ داده باشد.")
        return ConversationHandler.END

    result = result_row[output_unit].iloc[0]

    if pd.isna(result):
        await update.message.reply_text(f"خطا در محاسبه تبدیل. مقدار برای {input_unit} یافت نشد یا اینترپولیشن/اکسترپولیشن امکان‌پذیر نبود. ممکن است داده کافی برای محاسبه وجود نداشته باشد.")
        return ConversationHandler.END

    message_suffix = ""
    if is_extrapolation:
        message_suffix = "\n(توجه: این یک نتیجه برون‌یابی است، چون مقدار ورودی خارج از محدوده داده‌های موجود است.)"

    await update.message.reply_text(f"نتیجه تبدیل:\n{input_unit} = {value}\n{output_unit} = {result:.2f}{message_suffix}")

    return ConversationHandler.END


# ----------- main -----------
async def main(): # Make main function asynchronous
    global _telegram_bot_app

    # Stop the previous bot instance if it's running
    if _telegram_bot_app:
        print("Stopping previous bot instance...")
        await _telegram_bot_app.stop()
        _telegram_bot_app = None

    app = ApplicationBuilder().token("8558792228:AAH4FxuYnOmLxlnLYjGCoZmVRbCA7hnnaUI").build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_MODE: [CallbackQueryHandler(select_mode)],
            SELECT_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_type)],
            ENTER_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, convert_value)]
        },
        fallbacks=[]
    )

    app.add_handler(conv)
    _telegram_bot_app = app # Store the current app instance globally
    await app.run_polling() # Await the polling operation


if name == "__main__":
    # Apply nest_asyncio to allow asyncio.run() in an already running event loop
    nest_asyncio.apply()
    # Run the asynchronous main function
    asyncio.run(main())