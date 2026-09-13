export const SHIPMENT_STATUSES = [
  'ASSIGNED',
  'IN_TRANSIT',
  'DELIVERED',
  'NEEDS_REVIEW',
  'PROCESSING',
];

export const STATUS_CONFIG = {
  ASSIGNED: {
    badgeClass: 'border-amber-200 bg-amber-50 text-amber-800',
    dotClass: 'bg-amber-500',
  },
  CONFIRMED: {
    badgeClass: 'border-cyan-200 bg-cyan-50 text-cyan-800',
    dotClass: 'bg-cyan-500',
  },
  IN_TRANSIT: {
    badgeClass: 'border-blue-200 bg-blue-50 text-blue-800',
    dotClass: 'bg-blue-500',
  },
  DELIVERED: {
    badgeClass: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    dotClass: 'bg-emerald-500',
  },
  NEEDS_REVIEW: {
    badgeClass: 'border-rose-200 bg-rose-50 text-rose-800',
    dotClass: 'bg-rose-500',
  },
  PROCESSING: {
    badgeClass: 'border-violet-200 bg-violet-50 text-violet-800',
    dotClass: 'bg-violet-500',
  },
  FREE: {
    badgeClass: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    dotClass: 'bg-emerald-500',
  },
  OCCUPIED: {
    badgeClass: 'border-amber-200 bg-amber-50 text-amber-800',
    dotClass: 'bg-amber-500',
  },
};
