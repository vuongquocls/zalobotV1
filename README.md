# Zalo Telegram Bridge

Bot nay da chuyen sang kien truc theo mau `zalo-tg`: tien trinh Node.js ket noi truc tiep Zalo qua `zca-js` va ket noi Telegram qua `Telegraf`.

Zalo Web/Playwright cu khong con la runtime chinh.

## Cach hoat dong

- Moi chat ca nhan hoac nhom Zalo duoc map vao mot Telegram Forum Topic.
- Tin Zalo moi se tu tao topic neu chua co mapping.
- Tin nhan trong topic Telegram se duoc gui nguoc ve dung chat Zalo.
- Mapping topic duoc luu tai `data/topics.json`.
- Credential Zalo duoc luu tai `credentials.json` sau khi dang nhap QR.

## Tinh nang chinh

- Dong bo hai chieu Zalo <-> Telegram.
- Ho tro text, anh, video, file, voice, sticker, GIF, location, contact card va poll theo kha nang cua `zca-js`.
- Ho tro reply chain, reaction va thu hoi tin do bot gui.
- Tao topic DM bang `/search <ten>`.
- Dang nhap Zalo bang QR qua lenh `/login` trong Telegram.

## Cau hinh

```bash
cp .env.example .env
```

Bien bat buoc:

- `TG_TOKEN`: token Telegram bot tu BotFather.
- `TG_GROUP_ID`: ID supergroup Telegram da bat Topics.
- `ZALO_CREDENTIALS_PATH`: noi luu session Zalo, mac dinh `./credentials.json`.
- `DATA_DIR`: noi luu mapping, mac dinh `./data`.

## Cai dat

```bash
npm ci
npm run build
```

## Chay local

```bash
npm run dev
```

Neu chua co `credentials.json`, vao Telegram group va go:

```text
/login
```

Bot se gui QR Zalo vao Telegram de quet.

## Chay production

```bash
npm run build
npm start
```

Hoac dung PM2:

```bash
pm2 start pm2_zalo_bot.config.cjs --only zalo-bot --update-env
```

## Lenh Telegram

| Lenh | Mo ta |
| --- | --- |
| `/login` | Dang nhap Zalo bang QR |
| `/search <ten>` | Tim ban be Zalo va tao topic DM |
| `/recall` | Reply vao tin da gui tu Telegram roi thu hoi tren Zalo |
| `/topic list` | Liet ke mapping topic |
| `/topic info` | Xem mapping cua topic hien tai |
| `/topic delete` | Xoa mapping cua topic hien tai |

## Deploy

```bash
./deploy_and_run.sh
```

Script se cai dependency Node, build TypeScript, restart PM2 va in log gan nhat.
