module.exports = {
    apps: [{
        name: 'zalo-bot',
        script: 'zalo_bot.py',
        interpreter: '/root/zalobotV1/.venv/bin/python3',
        cwd: '/root/zalobotV1',
        env: {
            DISPLAY: ':99'
        },
        max_restarts: 10,
        restart_delay: 5000
    }]
};
