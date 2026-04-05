#!/bin/bash
cd /root/apex-system
export TELEGRAM_BOT_TOKEN=8779463548:AAEOawyBiAF2ryQ2ODnWpR4ZHt2rvC9B9do
export TELEGRAM_CHAT_ID=659650030
export APPS_SYSTEM_BOT_TOKEN=8779463548:AAEOawyBiAF2ryQ2ODnWpR4ZHt2rvC9B9do
export APPS_SYSTEM_BOT_CHAT_ID=659650030
while true; do
    python3 -m strategies.TEST_STRATEGY_01.strategy_main
    python3 -m modules.finalizer
    sleep 300
done
