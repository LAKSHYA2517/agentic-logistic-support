import { STATUS_CONFIG } from '../utils/constants';
import { getTranslations } from '../utils/i18n';

export function StatusBadge({ status, lang = 'en' }) {
  const t = getTranslations(lang);
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.PROCESSING;
  const label = t.statuses[status] || status || t.notAvailable;

  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${config.badgeClass}`}
    >
      <span className={`size-1.5 rounded-full ${config.dotClass}`} />
      {label}
    </span>
  );
}
