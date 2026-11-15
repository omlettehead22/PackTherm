// What the form calls each key of the study format, with its unit and a line
// of help. labels.test.ts checks that every key in the schema has an entry, so
// a key added to the study format cannot silently go missing from the form.
// Wording follows docs/STUDY_FILES.md.

export interface Label {
  label: string;
  unit?: string;
  help?: string;
  /** What an empty field means, for keys whose default is null. */
  empty?: string;
}

export const LABELS: Record<string, Label> = {
  // -- top level
  "top.packtherm_study": { label: "Format version" },
  "top.name": { label: "Study name", help: "Optional; shown with the results." },
  "top.cell": { label: "Cell" },
  "top.mode": { label: "Mode" },
  "top.ambient_C": { label: "Ambient temperature", unit: "°C", help: "Also the coolant's radiator inlet." },

  // -- duty
  "duty.type": { label: "Duty type" },
  "duty.rest_h": { label: "Rest after the event", unit: "h", help: "Simulated for recovery." },
  "duty.pack_kWh": {
    label: "Pack size",
    unit: "kWh",
    help: "Sets the EV duties' current and sizes pack-level cooling hardware.",
  },
  "duty.c_rate": { label: "Current", unit: "C" },
  "duty.direction": { label: "Direction" },
  "duty.soc0": {
    label: "Starting state of charge",
    unit: "0–1",
    empty: "Top of the window for a discharge, bottom for a charge",
  },
  "duty.soc_min": { label: "Lowest state of charge", unit: "0–1", help: "Current stops outside the window." },
  "duty.soc_max": { label: "Highest state of charge", unit: "0–1" },
  "duty.cycles": { label: "WLTC cycles", help: "Class 3b cycles back to back." },
  "duty.speed_kmh": { label: "Motorway speed", unit: "km/h", help: "Driven from 90 % to 10 %, then a rapid charge to 80 %." },
  "duty.charge_c_rate": { label: "Rapid-charge rate", unit: "C", empty: "The cell's maximum charge rate" },
  "duty.pack_V": { label: "Pack voltage", unit: "V", help: "For the series count." },
  "duty.steps": {
    label: "Segments",
    help: "Each segment: a duration and a current. Positive discharges, negative charges, 0 rests.",
  },
  "duty.name": { label: "Duty name", empty: "custom segments" },

  // -- requirements
  "requirements.T_max_C": {
    label: "Peak temperature limit",
    unit: "°C",
    empty: "The lower of 45 °C and the cell's datasheet limit",
  },
  "requirements.dT_cell_max_C": { label: "In-cell spread limit", unit: "°C" },
  "requirements.recovery_max_min": {
    label: "Ready again within",
    unit: "min",
    empty: "Within the rest window",
    help: "Near ambient, with any PCM re-frozen.",
  },
  "requirements.cell_to_cell_max_K": {
    label: "Cell-to-cell limit",
    unit: "K",
    empty: "Reported, not limited",
    help: "Hottest cell to coolest cell.",
  },

  // -- design space
  "design_space.topologies": { label: "Cooling" },
  "design_space.air_flows_g_s": { label: "Air flows", unit: "g/s per cell" },
  "design_space.coolant_flows_g_s": { label: "Coolant flows", unit: "g/s per cell" },
  "design_space.chiller_C": {
    label: "Chiller set-points",
    unit: "°C",
    help: "Leave empty for no chiller. Liquid designs also always run on the radiator; set-points at or above ambient are skipped.",
  },
  "design_space.fillers": { label: "Fillers between the cans", help: "-EG: with expanded graphite." },
  "design_space.gaps_mm": { label: "Gaps between cans", unit: "mm" },
  "design_space.packing": { label: "Packing" },

  // -- options
  "options.edge_cells": { label: "Simulate the cells on the module wall too" },
  "options.wall_U": { label: "Module wall heat transfer", unit: "W/m²K" },
  "options.r_margin": {
    label: "Worst-case resistance margin",
    unit: "fraction",
    help: "Above the datasheet maximum, for the re-check of the picks.",
  },
  "options.chiller_cop": { label: "Chiller COP", empty: "From ambient (Carnot fraction)" },
  "options.chiller_runs": { label: "Chiller runs" },
  "options.liquid_loop_kg": { label: "Liquid loop mass", unit: "kg per pack" },
  "options.air_system_kg": { label: "Air system mass", unit: "kg per pack" },
  "options.chiller_kg": { label: "Chiller mass", unit: "kg per pack" },

  // -- a user-defined cell
  "cell.name": { label: "Name" },
  "cell.format": { label: "Format", help: "Or give both sizes." },
  "cell.diameter_mm": { label: "Diameter", unit: "mm", empty: "From the format" },
  "cell.height_mm": { label: "Height", unit: "mm", empty: "From the format" },
  "cell.chemistry": { label: "Chemistry" },
  "cell.capacity_Ah": { label: "Capacity", unit: "Ah" },
  "cell.V_nominal": { label: "Nominal voltage", unit: "V" },
  "cell.mass_g": { label: "Mass", unit: "g" },
  "cell.DCIR_mOhm": {
    label: "DC resistance at 25 °C",
    unit: "mΩ",
    help: "DC, not the 1 kHz AC impedance, which is lower and under-predicts heat.",
  },
  "cell.DCIR_max_mOhm": { label: "Maximum DC resistance", unit: "mΩ", empty: "The DC resistance" },
  "cell.max_discharge_A": { label: "Maximum discharge current", unit: "A", empty: "Not checked" },
  "cell.max_charge_A": {
    label: "Maximum charge current",
    unit: "A",
    empty: "Not checked; a road trip charges at 1C",
  },
  "cell.T_max_charge_C": { label: "Maximum charging temperature", unit: "°C", empty: "None given" },
  "cell.T_max_discharge_C": { label: "Maximum discharge temperature", unit: "°C", empty: "None given" },
  "cell.cp_J_kgK": { label: "Heat capacity", unit: "J/kg·K", empty: "Jelly-roll value for the chemistry" },
  "cell.k_radial_W_mK": { label: "Radial conductivity", unit: "W/m·K", empty: "Jelly-roll value for the chemistry" },
  "cell.k_axial_W_mK": { label: "Axial conductivity", unit: "W/m·K", empty: "Jelly-roll value for the chemistry" },
  "cell.Ea_kJ_mol": {
    label: "Resistance activation energy",
    unit: "kJ/mol",
    empty: "20 (about ×2.1 from 25 to 0 °C)",
    help: "How fast resistance rises in the cold.",
  },
  "cell.entropic": { label: "Entropic heat" },
  "cell.source": { label: "Source", help: "Where the values come from; shown with the results." },
};

/** Words for the choices the format allows. */
export const CHOICE_LABELS: Record<string, string> = {
  constant: "Constant current",
  wltc: "WLTC city driving",
  roadtrip: "Motorway road trip",
  segments: "Custom segments",
  discharge: "Discharge",
  charge: "Charge",
  none: "None",
  air: "Forced air",
  bottom: "Cold plate (bottom)",
  ribbon: "Side ribbon",
  hex: "Hexagonal",
  square: "Square",
  event: "During the event only",
  always: "All the time",
  normal: "Normal",
  fast: "Fast",
  NMC: "NMC",
  NCA: "NCA",
  LFP: "LFP",
};

/** The topology "none" means a sealed module, not "no choice". */
export const TOPOLOGY_LABELS: Record<string, string> = {
  none: "Sealed (no cooling)",
  air: "Forced air",
  bottom: "Cold plate (bottom)",
  ribbon: "Side ribbon",
};

export const label = (path: string): Label => LABELS[path] ?? { label: path.split(".").pop() ?? path };
