#!/bin/bash
# Автоматическая установка и запуск бота

echo "🔹 Обновление пакетов..."
apt update && apt upgrade -y

echo "🔹 Установка зависимостей..."
apt install -y python3-pip git

echo "🔹 Клонирование репозитория..."
git clone https://github.com/ваш_репозиторий.git /root/telegram-bot
cd /root/telegram-bot

echo "🔹 Установка Python-модулей..."
pip3 install -r requirements.txt

echo "🔹 Настройка автозапуска..."
cp bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bot
systemctl start bot

echo "✅ Готово! Бот запущен."