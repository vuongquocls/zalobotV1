module.exports = {
  apps: [
    {
      name: "zalo-bot",
      cwd: __dirname,
      script: "zalo_bot.py",
      interpreter: `${__dirname}/.venv/bin/python`,
      exec_mode: "fork",
      instances: 1,
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 20,
      kill_timeout: 15000,
      watch: false,
      time: true,
      merge_logs: true,
      out_file: `${__dirname}/runtime-logs/zalo-bot-out.log`,
      error_file: `${__dirname}/runtime-logs/zalo-bot-error.log`,
      env: {
        DISPLAY: ":99",
        HEADLESS: "false",
        PYTHONUNBUFFERED: "1",
        APP_BUILD_ID: process.env.APP_BUILD_ID || "unknown",
      },
    },
  ],
};
