import React, { useState, useMemo } from 'react';
import { 
  Search, 
  ArrowUpDown, 
  Copy, 
  Check, 
  Truck 
} from 'lucide-react';
import { STATUS_CONFIG } from '../utils/constants';
import { formatCurrencyINR, formatRelativeTime } from '../utils/formatters';
import { TRANSLATIONS } from '../utils/i18n';

export function LedgerTable({
  shipments = [],
  highlightedIds = new Set(),
  onSelectShipment,
  lang = 'en',
  darkMode = false,
}) {
  const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [sortField, setSortField] = useState('updated_at');
  const [sortDirection, setSortDirection] = useState('desc');
  const [copiedId, setCopiedId] = useState(null);

  const handleCopy = (id, e) => {
    e.stopPropagation();
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const filteredShipments = useMemo(() => {
    return shipments.filter((item) => {
      const matchesSearch =
        item.id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        item.party_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        item.truck_number?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        item.origin?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        item.destination?.toLowerCase().includes(searchTerm.toLowerCase());

      const matchesStatus = statusFilter === 'ALL' || item.status === statusFilter;

      return matchesSearch && matchesStatus;
    }).sort((a, b) => {
      let aVal = a[sortField];
      let bVal = b[sortField];

      if (sortField === 'advance_paid' || sortField === 'balance_due') {
        aVal = Number(aVal) || 0;
        bVal = Number(bVal) || 0;
      } else if (sortField === 'updated_at') {
        aVal = new Date(aVal || 0).getTime();
        bVal = new Date(bVal || 0).getTime();
      } else {
        aVal = String(aVal || '').toLowerCase();
        bVal = String(bVal || '').toLowerCase();
      }

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
  }, [shipments, searchTerm, statusFilter, sortField, sortDirection]);

  const renderStatusBadge = (status) => {
    const config = STATUS_CONFIG[status] || {
      label: status,
      badgeClass: 'bg-slate-100 text-slate-800 border-slate-200',
      darkBadgeClass: 'bg-slate-800 text-slate-300 border-slate-700',
    };
    const localizedLabel = t[status] || config.label;
    const badgeStyle = darkMode ? (config.darkBadgeClass || config.badgeClass) : config.badgeClass;

    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${badgeStyle}`}>
        {localizedLabel}
      </span>
    );
  };

  return (
    <div className={`rounded-lg border shadow-xs overflow-hidden transition-colors ${
      darkMode ? 'bg-[#111827] border-slate-800' : 'bg-white border-slate-200'
    }`}>
      {/* Filter Toolbar */}
      <div className={`p-3 border-b flex flex-col sm:flex-row gap-3 sm:items-center justify-between ${
        darkMode ? 'bg-[#0b0f19] border-slate-800' : 'bg-slate-50/80 border-slate-200'
      }`}>
        {/* Search */}
        <div className="relative flex-1 max-w-sm">
          <Search className={`size-4 absolute left-3 top-1/2 -translate-y-1/2 ${
            darkMode ? 'text-slate-500' : 'text-slate-400'
          }`} strokeWidth={1.5} />
          <input
            type="text"
            placeholder={t.searchPlaceholder}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className={`w-full pl-9 pr-3 py-1.5 text-xs rounded-md border outline-none transition-colors ${
              darkMode 
                ? 'bg-[#131b2e] border-slate-700 text-white placeholder-slate-500 focus:border-slate-500 focus:ring-1 focus:ring-slate-600'
                : 'bg-white border-slate-200 text-slate-900 placeholder-slate-400 focus:border-slate-400 focus:ring-1 focus:ring-slate-300'
            }`}
          />
        </div>

        {/* Status Filter Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto text-xs">
          {['ALL', 'IN_TRANSIT', 'PENDING_LOADING', 'DELAYED', 'DELIVERED'].map((st) => {
            const isActive = statusFilter === st;
            const label = st === 'ALL' ? t.filterAll : (t[st] || STATUS_CONFIG[st]?.label || st);
            return (
              <button
                key={st}
                onClick={() => setStatusFilter(st)}
                className={`px-2.5 py-1 rounded text-xs font-medium transition-colors cursor-pointer whitespace-nowrap border ${
                  isActive
                    ? darkMode ? 'bg-slate-800 text-white border-slate-700 shadow-xs' : 'bg-slate-900 text-white border-slate-900 shadow-xs'
                    : darkMode ? 'bg-[#131b2e] border-slate-800 text-slate-400 hover:bg-slate-800 hover:text-slate-200' : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Table Element */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse table-fixed min-w-[760px]">
          <thead>
            <tr className={`text-xs font-bold uppercase tracking-wider py-3 px-4 border-b select-none ${
              darkMode ? 'bg-[#0f172a] text-slate-400 border-slate-800' : 'bg-slate-100/90 text-slate-600 border-slate-200'
            }`}>
              <th 
                className="w-[130px] py-3 px-4 cursor-pointer hover:text-white"
                onClick={() => handleSort('id')}
              >
                <div className="flex items-center gap-1">
                  <span>{t.orderId}</span>
                  <ArrowUpDown className="size-3 text-slate-400" strokeWidth={1.5} />
                </div>
              </th>
              <th 
                className="w-[240px] py-3 px-4 cursor-pointer hover:text-white"
                onClick={() => handleSort('party_name')}
              >
                <div className="flex items-center gap-1">
                  <span>{t.partyName}</span>
                  <ArrowUpDown className="size-3 text-slate-400" strokeWidth={1.5} />
                </div>
              </th>
              <th 
                className="w-[150px] py-3 px-4 cursor-pointer hover:text-white"
                onClick={() => handleSort('truck_number')}
              >
                <div className="flex items-center gap-1">
                  <span>{t.truckNumber}</span>
                  <ArrowUpDown className="size-3 text-slate-400" strokeWidth={1.5} />
                </div>
              </th>
              <th 
                className="w-[130px] py-3 px-4 text-right cursor-pointer hover:text-white"
                onClick={() => handleSort('advance_paid')}
              >
                <div className="flex items-center justify-end gap-1">
                  <span>{t.advancePaid}</span>
                  <ArrowUpDown className="size-3 text-slate-400" strokeWidth={1.5} />
                </div>
              </th>
              <th 
                className="w-[130px] py-3 px-4 text-right cursor-pointer hover:text-white"
                onClick={() => handleSort('balance_due')}
              >
                <div className="flex items-center justify-end gap-1">
                  <span>{t.balanceDue}</span>
                  <ArrowUpDown className="size-3 text-slate-400" strokeWidth={1.5} />
                </div>
              </th>
              <th 
                className="w-[150px] py-3 px-4 cursor-pointer hover:text-white"
                onClick={() => handleSort('status')}
              >
                <div className="flex items-center gap-1">
                  <span>{t.statusCol}</span>
                  <ArrowUpDown className="size-3 text-slate-400" strokeWidth={1.5} />
                </div>
              </th>
            </tr>
          </thead>
          <tbody className={`divide-y text-xs ${
            darkMode ? 'divide-slate-800 text-slate-200' : 'divide-slate-100 text-slate-800'
          }`}>
            {filteredShipments.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-14 text-center text-slate-500">
                  <div className="flex flex-col items-center justify-center gap-2 max-w-sm mx-auto">
                    <Truck className="size-7 text-slate-400" strokeWidth={1.5} />
                    <p className={`font-semibold text-xs ${darkMode ? 'text-slate-300' : 'text-slate-800'}`}>
                      {shipments.length === 0 ? t.noShipmentsTitle : t.noMatchingTitle}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {shipments.length === 0 ? t.noShipmentsSub : t.noMatchingSub}
                    </p>
                  </div>
                </td>
              </tr>
            ) : (
              filteredShipments.map((shipment) => {
                const isNewlyHighlighted = highlightedIds.has(shipment.id);

                return (
                  <tr
                    key={shipment.id}
                    onClick={() => onSelectShipment && onSelectShipment(shipment)}
                    className={`transition-colors cursor-pointer border-b ${
                      darkMode ? 'hover:bg-slate-800/40 border-slate-800/60' : 'hover:bg-slate-50/80 border-slate-100'
                    } ${isNewlyHighlighted ? 'animate-amber-flash' : ''}`}
                  >
                    {/* Order ID */}
                    <td className="py-2.5 px-4">
                      <div className="flex items-center gap-1.5">
                        <span className={`font-mono text-xs px-2 py-0.5 rounded border font-semibold ${
                          darkMode ? 'bg-slate-800 text-slate-200 border-slate-700' : 'bg-slate-100 text-slate-800 border-slate-200'
                        }`}>
                          {shipment.id}
                        </span>
                        <button
                          title="Copy ID"
                          onClick={(e) => handleCopy(shipment.id, e)}
                          className={`p-0.5 rounded cursor-pointer ${
                            darkMode ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-700'
                          }`}
                        >
                          {copiedId === shipment.id ? (
                            <Check className="size-3 text-emerald-500" strokeWidth={2} />
                          ) : (
                            <Copy className="size-3" strokeWidth={1.5} />
                          )}
                        </button>
                      </div>
                    </td>

                    {/* Party Name */}
                    <td className="py-2.5 px-4">
                      <div className={`font-semibold truncate ${darkMode ? 'text-white' : 'text-slate-900'}`}>
                        {shipment.party_name}
                      </div>
                      {(shipment.origin || shipment.destination) && (
                        <div className="text-[11px] text-slate-400 truncate">
                          {shipment.origin} → {shipment.destination}
                        </div>
                      )}
                    </td>

                    {/* Truck Number */}
                    <td className="py-2.5 px-4">
                      <span className={`font-mono text-xs px-2 py-0.5 rounded border font-semibold ${
                        darkMode ? 'bg-slate-800 text-slate-200 border-slate-700' : 'bg-slate-100 text-slate-800 border-slate-200'
                      }`}>
                        {shipment.truck_number}
                      </span>
                    </td>

                    {/* Advance Paid */}
                    <td className={`py-2.5 px-4 text-right font-mono text-xs font-semibold ${
                      darkMode ? 'text-white' : 'text-slate-900'
                    }`}>
                      {formatCurrencyINR(shipment.advance_paid)}
                    </td>

                    {/* Balance Due */}
                    <td className={`py-2.5 px-4 text-right font-mono text-xs font-semibold ${
                      darkMode ? 'text-slate-300' : 'text-slate-700'
                    }`}>
                      {formatCurrencyINR(shipment.balance_due)}
                    </td>

                    {/* Status */}
                    <td className="py-2.5 px-4">
                      {renderStatusBadge(shipment.status)}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Footer summary bar */}
      <div className={`py-2.5 px-4 border-t flex items-center justify-between text-[11px] ${
        darkMode ? 'border-slate-800 bg-[#0b0f19] text-slate-400' : 'border-slate-200 bg-slate-50/80 text-slate-500'
      }`}>
        <span>
          {t.showingShipments(filteredShipments.length, shipments.length)}
        </span>
        <span className="font-mono text-[10px] text-slate-500">
          {t.wsStreamActive}
        </span>
      </div>
    </div>
  );
}
