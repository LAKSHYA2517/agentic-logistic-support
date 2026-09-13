import { Languages, Truck } from 'lucide-react';
import { getTranslations, LANGUAGES } from '../utils/i18n';

export function Header({
  activeSection = 'overview',
  onNavigate,
  apiStatus = 'loading',
  lang = 'en',
  onLanguageChange,
}) {
  const t = getTranslations(lang);
  const navigation = [
    { id: 'overview', label: t.navOverview },
    { id: 'shipments', label: t.navShipments },
    { id: 'drivers', label: t.navDrivers },
  ];

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 text-slate-900 shadow-sm backdrop-blur">
      <div className="mx-auto flex min-h-16 max-w-[1440px] flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3 sm:px-6 lg:px-8">
        <button
          type="button"
          onClick={() => onNavigate('overview')}
          className="flex shrink-0 items-center gap-3 text-left"
          aria-label={t.navOverview}
        >
          <span className="grid size-9 place-items-center rounded-lg bg-amber-500 text-white">
            <Truck className="size-5" strokeWidth={2.2} />
          </span>
          <span>
            <span className="block text-sm font-bold tracking-tight">Sauda Logistics</span>
            <span className="block text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              {t.brandSubtitle}
            </span>
          </span>
        </button>

        <nav className="order-3 flex w-full items-center gap-1 overflow-x-auto border-t border-slate-100 pt-2 sm:order-none sm:w-auto sm:border-0 sm:pt-0" aria-label={t.mainNavigation}>
          {navigation.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onNavigate(item.id)}
              className={`whitespace-nowrap rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                activeSection === item.id
                  ? 'bg-amber-50 text-amber-800 ring-1 ring-amber-200'
                  : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <div className="hidden items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-[11px] font-medium sm:flex">
            <span
              className={`size-2 rounded-full ${
                apiStatus === 'online'
                  ? 'bg-emerald-500'
                  : apiStatus === 'loading'
                    ? 'bg-amber-400'
                    : 'bg-rose-400'
              }`}
            />
            <span className="text-slate-600">
              {apiStatus === 'online'
                ? t.apiOnline
                : apiStatus === 'loading'
                  ? t.apiLoading
                  : t.apiOffline}
            </span>
          </div>

          <label className="relative flex items-center" aria-label={t.language}>
            <Languages className="pointer-events-none absolute left-2.5 size-3.5 text-slate-400" />
            <select
              value={lang}
              onChange={(event) => onLanguageChange(event.target.value)}
              className="h-9 max-w-[132px] appearance-none rounded-lg border border-slate-200 bg-white py-1 pl-8 pr-7 text-xs font-medium text-slate-700 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20 sm:max-w-none"
            >
              {LANGUAGES.map((language) => (
                <option key={language.code} value={language.code}>
                  {language.label}
                </option>
              ))}
            </select>
            <span className="pointer-events-none absolute right-2 text-[9px] text-slate-500">▼</span>
          </label>

        </div>
      </div>
    </header>
  );
}
