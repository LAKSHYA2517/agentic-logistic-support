export const STATUS_CONFIG = {
  IN_TRANSIT: {
    label: 'In Transit',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-200/80',
    darkBadgeClass: 'bg-blue-950/80 text-blue-300 border-blue-800/60',
    dotClass: 'bg-blue-600',
  },
  PENDING_LOADING: {
    label: 'Pending Loading',
    badgeClass: 'bg-amber-100 text-amber-800 border-amber-200/80',
    darkBadgeClass: 'bg-amber-950/80 text-amber-300 border-amber-800/60',
    dotClass: 'bg-amber-600',
  },
  DELIVERED: {
    label: 'Delivered',
    badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-200/80',
    darkBadgeClass: 'bg-emerald-950/80 text-emerald-300 border-emerald-800/60',
    dotClass: 'bg-emerald-600',
  },
  DELAYED: {
    label: 'Delayed',
    badgeClass: 'bg-rose-100 text-rose-800 border-rose-200/80',
    darkBadgeClass: 'bg-rose-950/80 text-rose-300 border-rose-800/60',
    dotClass: 'bg-rose-600',
  },
  PAYMENT_PENDING: {
    label: 'Payment Pending',
    badgeClass: 'bg-amber-100 text-amber-800 border-amber-200/80',
    darkBadgeClass: 'bg-amber-950/80 text-amber-300 border-amber-800/60',
    dotClass: 'bg-amber-600',
  },
};

export const INITIAL_MOCK_SHIPMENTS = [];

export const PARTIES = [
  "Ramesh Logistics & Cargo",
  "Sharma Cement & Minerals Ltd.",
  "Patel Agro Products Pvt Ltd",
  "Gupta Steel & Infrastructure",
  "Balaji Chemical Carriers",
  "Khandelwal Metal Works",
  "Venkateshwara Cold Chain",
  "Singhania Paper Mills",
  "Om Sai Freight Forwarders",
  "Maharaja Express Lines",
  "Navkar Textiles & Yarn",
  "Hindustan Fertilizer Transport",
  "Apex Heavy Haulage",
  "Siddhivinayak Roadways",
  "Tirupati Coal Carriers",
  "Blue Dart Heavy Cargo",
  "Maruti Supply Chain Solutions",
  "Goyal Ceramic Tiles",
  "Tata BlueScope Cargo",
  "Surat Diamond Express Logistics",
];

export const ROUTES = [
  { origin: "Jaipur, RJ", destination: "Bhiwandi, MH" },
  { origin: "Ahmedabad, GJ", destination: "Indore, MP" },
  { origin: "Kotputli, RJ", destination: "Noida, UP" },
  { origin: "Raigad, MH", destination: "Nagpur, MH" },
  { origin: "Panipat, HR", destination: "Baddi, HP" },
  { origin: "Bengaluru, KA", destination: "Hyderabad, TS" },
  { origin: "Lucknow, UP", destination: "Kanpur, UP" },
  { origin: "Mumbai Port, MH", destination: "Pune MIDC, MH" },
  { origin: "Ludhiana, PB", destination: "Gurugram, HR" },
  { origin: "Surat, GJ", destination: "Kolkata, WB" },
  { origin: "Chennai, TN", destination: "Coimbatore, TN" },
  { origin: "Visakhapatnam, AP", destination: "Raipur, CG" },
  { origin: "Jamshedpur, JH", destination: "Bhubaneswar, OD" },
];

export const STATE_CODES = ["RJ", "DL", "MH", "GJ", "HR", "UP", "KA", "TN", "PB", "WB"];

export function generateRandomIndianPlate() {
  const state = STATE_CODES[Math.floor(Math.random() * STATE_CODES.length)];
  const district = String(Math.floor(1 + Math.random() * 50)).padStart(2, "0");
  const letters = String.fromCharCode(65 + Math.floor(Math.random() * 26)) + 
                  String.fromCharCode(65 + Math.floor(Math.random() * 26));
  const num = Math.floor(1000 + Math.random() * 9000);
  return `${state}${district}${letters}${num}`;
}

export function generateDynamicVoicePayload() {
  const party = PARTIES[Math.floor(Math.random() * PARTIES.length)];
  const route = ROUTES[Math.floor(Math.random() * ROUTES.length)];
  const truck = generateRandomIndianPlate();
  const orderId = `SHP-${Math.floor(1000 + Math.random() * 9000)}`;

  const statuses = ["IN_TRANSIT", "IN_TRANSIT", "PENDING_LOADING", "DELAYED", "DELIVERED"];
  const status = statuses[Math.floor(Math.random() * statuses.length)];

  const advancePaid = Math.floor((Math.random() * 8 + 2)) * 5000;
  let balanceDue = 0;
  if (status !== "DELIVERED") {
    balanceDue = Math.floor((Math.random() * 10 + 3)) * 5000;
  }

  const transcripts = [
    `Gaadi ${truck} nikal chuki hai ${route.origin} se ${route.destination}. Party ${party} advance ₹${advancePaid.toLocaleString('en-IN')}, balance ₹${balanceDue.toLocaleString('en-IN')}.`,
    `Voice note: ${truck} loaded at ${route.origin}. Cash advance of ₹${advancePaid.toLocaleString('en-IN')} paid. Balance ₹${balanceDue.toLocaleString('en-IN')} upon delivery.`,
    `Transport dispatch: ${party} shipment confirmed. Truck ${truck}, advance ₹${advancePaid.toLocaleString('en-IN')}, balance ₹${balanceDue.toLocaleString('en-IN')}. Status: ${status}.`,
  ];

  const transcript = transcripts[Math.floor(Math.random() * transcripts.length)];

  return {
    event: "SHIPMENT_UPDATED",
    data: {
      id: orderId,
      party_name: party,
      truck_number: truck,
      advance_paid: advancePaid,
      balance_due: balanceDue,
      status: status,
      origin: route.origin,
      destination: route.destination,
      updated_at: new Date().toISOString(),
      source_voice_note: transcript,
    },
  };
}
