const VN_OFFSET_MS = 7 * 60 * 60 * 1000;
const VN_WEEKDAY_NAMES = [
  'Chủ nhật',
  'thứ Hai',
  'thứ Ba',
  'thứ Tư',
  'thứ Năm',
  'thứ Sáu',
  'thứ Bảy',
] as const;

export interface ParsedReminder {
  remindAt: Date;
  text: string;
}

function normalizeVietnamese(input: string): string {
  return input
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/\s+/g, ' ')
    .trim();
}

function vietnamParts(date: Date): { year: number; month: number; day: number; hour: number; minute: number; weekday: number } {
  const vn = new Date(date.getTime() + VN_OFFSET_MS);
  return {
    year: vn.getUTCFullYear(),
    month: vn.getUTCMonth() + 1,
    day: vn.getUTCDate(),
    hour: vn.getUTCHours(),
    minute: vn.getUTCMinutes(),
    weekday: vn.getUTCDay(),
  };
}

function vietnamDateTimeToUtc(year: number, month: number, day: number, hour: number, minute: number): Date {
  return new Date(Date.UTC(year, month - 1, day, hour, minute) - VN_OFFSET_MS);
}

function addVietnamDays(now: Date, days: number, hour: number, minute: number): Date {
  const parts = vietnamParts(now);
  return vietnamDateTimeToUtc(parts.year, parts.month, parts.day + days, hour, minute);
}

function vietnamWeekdayFromMonday(now: Date): number {
  const weekday = vietnamParts(now).weekday;
  return weekday === 0 ? 6 : weekday - 1;
}

function weekdayFromNormalizedText(text: string): number | null {
  if (/\b(chu\s*nhat|cn)\b/.test(text)) return 6;
  const match = text.match(/\bthu\s*(2|hai|3|ba|4|tu|5|nam|6|sau|7|bay)\b/);
  if (!match) return null;

  const token = match[1];
  if (token === '2' || token === 'hai') return 0;
  if (token === '3' || token === 'ba') return 1;
  if (token === '4' || token === 'tu') return 2;
  if (token === '5' || token === 'nam') return 3;
  if (token === '6' || token === 'sau') return 4;
  if (token === '7' || token === 'bay') return 5;
  return null;
}

function parseTime(normalized: string): { hour: number; minute: number } | null {
  const explicit = normalized.match(/(?:luc|vao luc|vao|lúc)\s*(\d{1,2})(?::|h| gio)?\s*(\d{2})?/);
  const fallback = normalized.match(/\b(\d{1,2})(?::|h)(\d{2})\b/);
  const match = explicit ?? fallback;
  if (!match) return null;

  let hour = Number(match[1]);
  const minute = match[2] ? Number(match[2]) : 0;
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) return null;
  if (minute < 0 || minute > 59) return null;

  const afterTime = normalized.slice((match.index ?? 0) + match[0].length);
  const beforeTime = normalized.slice(0, match.index ?? 0);
  const aroundTime = `${beforeTime.slice(-20)} ${afterTime.slice(0, 20)}`;
  if (hour >= 1 && hour <= 11 && /\b(chieu|toi|dem)\b/.test(aroundTime)) {
    hour += 12;
  }
  if (hour === 12 && /\b(sang)\b/.test(aroundTime)) {
    hour = 0;
  }
  if (hour < 0 || hour > 23) return null;
  return { hour, minute };
}

function parseDate(normalized: string, now: Date, hour: number, minute: number): Date {
  const nowParts = vietnamParts(now);
  const explicitDate = normalized.match(/\b(\d{1,2})[\/.-](\d{1,2})(?:[\/.-](\d{2,4}))?\b/);
  if (explicitDate) {
    const day = Number(explicitDate[1]);
    const month = Number(explicitDate[2]);
    let year = explicitDate[3] ? Number(explicitDate[3]) : nowParts.year;
    if (year < 100) year += 2000;
    return vietnamDateTimeToUtc(year, month, day, hour, minute);
  }

  if (/\b(ngay kia|mốt|mot)\b/.test(normalized)) {
    return addVietnamDays(now, 2, hour, minute);
  }
  if (/\b(mai|ngay mai|sang mai|toi mai|chieu mai)\b/.test(normalized)) {
    return addVietnamDays(now, 1, hour, minute);
  }
  if (/\b(hom nay|toi nay|chieu nay|sang nay)\b/.test(normalized)) {
    return addVietnamDays(now, 0, hour, minute);
  }

  const weekdayDate = normalized.match(/\b(?:(?:thu\s*(?:2|hai|3|ba|4|tu|5|nam|6|sau|7|bay))|(?:chu\s*nhat)|cn)\b(?:\s+tuan\s+(nay|sau|toi|ke))?/);
  if (weekdayDate) {
    const targetWeekday = weekdayFromNormalizedText(weekdayDate[0]);
    if (targetWeekday !== null) {
      const currentWeekday = vietnamWeekdayFromMonday(now);
      let days: number;

      if (/\btuan\s+(sau|toi|ke)\b/.test(weekdayDate[0])) {
        days = 7 - currentWeekday + targetWeekday;
      } else if (/\btuan\s+nay\b/.test(weekdayDate[0])) {
        days = targetWeekday - currentWeekday;
      } else {
        days = (targetWeekday - currentWeekday + 7) % 7;
        const candidate = addVietnamDays(now, days, hour, minute);
        if (candidate.getTime() <= now.getTime() + 30_000) {
          days += 7;
        }
      }

      return addVietnamDays(now, days, hour, minute);
    }
  }

  const today = addVietnamDays(now, 0, hour, minute);
  return today.getTime() > now.getTime() ? today : addVietnamDays(now, 1, hour, minute);
}

const WEEKDAY_PHRASE_RE = /\b(?:(?:thứ|thu)\s*(?:hai|2|ba|3|tư|tu|4|năm|nam|5|sáu|sau|6|bảy|bay|7)|(?:chủ\s*nhật|chu\s*nhat|cn))\b(?:\s+(?:tuần|tuan)\s+(?:này|nay|sau|tới|toi|kế|ke))?/gi;

function extractReminderText(original: string): string {
  let text = original
    .replace(/^\s*@?[\p{L}\p{N}_-]+\s+(ơi|oi)[,\s]+/iu, '')
    .replace(/^\s*@?[\p{L}\p{N}_-]+[,\s]+(?=(nhac|nhắc|hen|hẹn))/iu, '')
    .replace(/^\s*(em|bot|hermes|zalo bot)[,\s]+/i, '')
    .replace(/^\s*(?:(?:tạo|tao|đặt|dat)\s+(?:lịch\s+|lich\s+)?)?(?:nhắc hẹn|nhac hen|nhắc|nhac)\s+(?:cho\s+)?(?:anh|tôi|toi|mình|minh|em|tớ|to)?\b/i, '')
    .replace(/\b(nội dung|noi dung)\s*:\s*/gi, '')
    .replace(/\b(thời gian|thoi gian)\s*:\s*/gi, '')
    .replace(/\b(nhac hen|nhắc hẹn|nhac|nhắc)\s+(mọi người|moi nguoi|cả nhóm|ca nhom|nhóm|nhom|anh em|ae)\b/i, '$2')
    .replace(/\b(nhac hen|nhắc hẹn|nhac|nhắc)\s+(anh|tôi|toi|mình|minh|em|tớ|to)\b/i, '')
    .replace(/\b(giúp anh|giup anh|giùm anh|gium anh|hộ anh|ho anh)\b/i, '')
    .replace(/\b(vào lúc|vao luc|lúc|luc)\s*\d{1,2}(?::|h| giờ)?\s*\d{0,2}\b/gi, '')
    .replace(/\b\d{1,2}(?::|h)\d{2}\b/g, '')
    .replace(/\b(ngày mai|ngay mai|sáng mai|sang mai|tối mai|toi mai|chiều mai|chieu mai|hôm nay|hom nay|ngày kia|ngay kia|mốt|mot)\b/gi, '')
    .replace(WEEKDAY_PHRASE_RE, '')
    .replace(/\b\d{1,2}[\/.-]\d{1,2}(?:[\/.-]\d{2,4})?\b/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[ ,.;:-]+$/g, '');

  text = text.replace(/^(rằng|rang|là|la|:|-)\s+/i, '').trim();
  return text || 'việc anh đã hẹn';
}

export function isReminderCapabilityQuestion(input: string): boolean {
  const normalized = normalizeVietnamese(input);
  return /\b(co|có)\s+(chuc nang|tinh nang)?\s*nhac/.test(normalized)
    || /\bnhac hen\b/.test(normalized) && /\b(duoc khong|khong|chua co|co khong)\b/.test(normalized);
}

export function parseReminderRequest(input: string, now = new Date()): ParsedReminder | null {
  const normalized = normalizeVietnamese(input);
  if (!/\b(nhac|hen|nhac hen)\b/.test(normalized)) return null;
  if (!/\b(anh|toi|minh|em|to|moi nguoi|ca nhom|nhom|anh em|ae)\b/.test(normalized)) return null;

  const parsedTime = parseTime(normalized);
  if (!parsedTime) return null;

  const remindAt = parseDate(normalized, now, parsedTime.hour, parsedTime.minute);
  if (remindAt.getTime() <= now.getTime() + 30_000) return null;

  return {
    remindAt,
    text: extractReminderText(input),
  };
}

export function formatVietnamDateTime(date: Date): string {
  const parts = vietnamParts(date);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(parts.hour)}:${pad(parts.minute)} ${VN_WEEKDAY_NAMES[parts.weekday]}, ngày ${pad(parts.day)}/${pad(parts.month)}/${parts.year}`;
}
