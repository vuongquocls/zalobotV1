module.exports = {
    apps: [{
        name: 'zalo-bot',
        script: 'dist/index.js',
        interpreter: 'node',
        cwd: '/root/zalobotV1',
        env: {
            TZ: 'Asia/Ho_Chi_Minh'
        },
        max_restarts: 10,
        restart_delay: 5000
    }]
};
