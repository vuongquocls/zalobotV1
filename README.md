# Zalo Hermes Gateway

Bot nay da chuyen sang kien truc theo mau `zalo-tg`: tien trinh Node.js ket noi truc tiep Zalo qua `zca-js` va ket noi Telegram qua `Telegraf`.

Ban moi them lop Hermes Gateway: tin Zalo text co the duoc gui vao Hermes Core dung chung de quyet dinh tu tra loi, xin anh duyet tren Telegram, bo qua, hoac fallback ve bridge cu.

Zalo Web/Playwright cu khong con la runtime chinh.

## Cach hoat dong

- Moi chat ca nhan hoac nhom Zalo duoc map vao mot Telegram Forum Topic.
- Tin Zalo moi se tu tao topic neu chua co mapping.
- Tin nhan trong topic Telegram se duoc gui nguoc ve dung chat Zalo.
- Mapping topic duoc luu tai `data/topics.json`.
- Credential Zalo duoc luu tai `credentials.json` sau khi dang nhap QR.
- Chat 1:1 Zalo luon duoc gui vao Hermes neu `HERMES_CORE_URL` duoc cau hinh.
- Tin trong nhom Zalo chi duoc gui vao Hermes khi co alias nhu `hermes`, `zalo bot`, `bot` de tranh bot chen vao moi cuoc tro chuyen.
- Khi Hermes can duyet, bot gui ban nhap sang Telegram approval group voi nut `Duyet gui Zalo` / `Tu choi`.

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

Bien Hermes tuy chon:

- `HERMES_CORE_URL`: URL Hermes decision API, vi du `http://127.0.0.1:8765`. De trong thi bot chay nhu bridge cu.
- `HERMES_CORE_TIMEOUT_MS`: timeout goi Hermes Core, mac dinh `8000`.
- `ZALO_BOT_ALIASES`: danh sach ten goi bot trong nhom Zalo, cach nhau bang dau phay.
- `TG_APPROVAL_GROUP_ID`: group Telegram nhan yeu cau duyet, mac dinh bang `TG_GROUP_ID`.
- `TG_APPROVER_USER_IDS`: danh sach Telegram user id duoc bam duyet, cach nhau bang dau phay. De trong thi khong gioi han trong group duyet.

Hermes Core endpoint mau nam trong repo `YokDon-Telegram-Office`:

```bash
cd /Users/mt/Antigranvity/YokDon-Telegram-Office
python3 scripts/run_zalo_decision_api.py
```

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
