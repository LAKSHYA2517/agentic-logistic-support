const LOCALES = {
  en: 'en-IN',
  hi: 'hi-IN',
  ta: 'ta-IN',
  pa: 'pa-IN',
};

export function formatCurrencyINR(amount, language = 'en') {
  const numericAmount = Number(amount);
  if (!Number.isFinite(numericAmount)) return '₹0';
  return new Intl.NumberFormat(LOCALES[language] || LOCALES.en, {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(numericAmount);
}

export function formatDateTime(value, language = 'en') {
  if (!value) return '—';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(LOCALES[language] || LOCALES.en, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

export function formatPhoneNumber(value) {
  if (!value) return '—';
  const digits = String(value).replace(/\D/g, '');
  const nationalNumber = digits.length === 12 && digits.startsWith('91')
    ? digits.slice(2)
    : digits;
  if (nationalNumber.length === 10) {
    return `+91 ${nationalNumber.slice(0, 5)} ${nationalNumber.slice(5)}`;
  }
  return String(value).startsWith('+') ? String(value) : `+${digits}`;
}
