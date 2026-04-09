import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_BASE = import.meta.env.VITE_API_BASE || "";

const ARTIFACTS = [
  "generated_crystals.extxyz",
  "generated_trajectories.zip",
  "generated_crystals_cif.zip",
];

const VASP_EXECUTABLES = ["vasp_std", "vasp_gam", "vasp_ncl"];
const VASP_DEFAULT_NPROC = 16;
const DEFAULT_WANNIER_PLOT_FORMAT = "cube";
const VASP_RUN_MODES = [
  { value: "standard", label: "HDF5 standard" },
  { value: "vtst_neb", label: "VTST NEB" },
  { value: "wannier_scf", label: "Wannier SCF" },
  { value: "wannier_post", label: "Wannier post" },
];
const VTST_MODE_OPTIONS = [
  {
    value: "pre_relaxed",
    label: "Pre-relaxed endpoints",
    description: "Use uploaded POSCAR_i and POSCAR_f directly as the NEB endpoints.",
  },
  {
    value: "relax_first",
    label: "Relax endpoints first",
    description: "Relax the uploaded endpoint guesses before building the NEB path.",
  },
];
const VTST_SHARED_OUTPUTS = [
  "vasprun.xml",
  "vasp.out",
  "OUTCAR",
  "vaspout.h5",
  "neb.dat",
  "spline.dat",
  "exts.dat",
  "nebresults.txt",
  "POSCAR_initial",
  "POSCAR_final",
  "vtst_metrics.json",
  "image_energy_table.csv",
  "plots/barrier_raw.png",
  "plots/barrier_spline.png",
  "plots/force_along_path.png",
  "plots/reaction_movie.gif",
  "plots/endpoint_vs_ts.png",
  "endpoint_initial_vasp.out",
  "endpoint_initial_OUTCAR",
  "endpoint_initial_vasprun.xml",
  "endpoint_initial_vaspout.h5",
  "endpoint_final_vasp.out",
  "endpoint_final_OUTCAR",
  "endpoint_final_vasprun.xml",
  "endpoint_final_vaspout.h5",
];
const VTST_MODE_CONFIG = {
  pre_relaxed: {
    required: ["INCAR_neb", "KPOINTS", "POTCAR", "POSCAR_i", "POSCAR_f"],
    optional: ["CHGCAR", "WAVECAR"],
    outputs: VTST_SHARED_OUTPUTS,
    dropTitle: "Drop VTST NEB inputs here",
    dropHint: "Req: INCAR_neb, KPOINTS, POTCAR, POSCAR_i, POSCAR_f",
    description:
      "Use already relaxed endpoints directly. Backend runs nebmake.pl and the parent NEB or CI-NEB job only.",
    detail:
      "Backend copies INCAR_neb to the working INCAR, builds images with nebmake.pl, then parses neb.dat, spline.dat, and exts.dat in one pipeline.",
  },
  relax_first: {
    required: ["INCAR_endpoint", "INCAR_neb", "KPOINTS", "POTCAR", "POSCAR_i", "POSCAR_f"],
    optional: ["CHGCAR", "WAVECAR"],
    outputs: VTST_SHARED_OUTPUTS,
    dropTitle: "Drop VTST NEB inputs here",
    dropHint:
      "Req: INCAR_endpoint, INCAR_neb, KPOINTS, POTCAR, POSCAR_i, POSCAR_f",
    description:
      "Relax both endpoints first, then build the NEB path from the relaxed CONTCAR files.",
    detail:
      "Backend runs endpoint relaxations in endpoint_initial/ and endpoint_final/, promotes CONTCAR to POSCAR_initial and POSCAR_final, then launches nebmake.pl and the parent NEB or CI-NEB job.",
  },
};
const getVtstModeConfig = (vtstMode) =>
  VTST_MODE_CONFIG[vtstMode] || VTST_MODE_CONFIG.pre_relaxed;
const VASP_MODE_CONFIG = {
  standard: {
    label: "HDF5 standard",
    required: ["INCAR", "POSCAR", "POTCAR", "KPOINTS"],
    optional: ["CHGCAR", "WAVECAR"],
    outputs: [
      "vasprun.xml",
      "vasp.out",
      "OUTCAR",
      "vaspout.h5",
      "HDF5_metrics.json",
      "plots/energy.png",
      "plots/dos.png",
      "plots/band.png",
      "plots/phonon_dos.png",
      "plots/phonon_band.png",
      "plots/magnetism.png",
    ],
    dropTitle: "Drop standard VASP inputs here",
    dropHint: "Req: INCAR, POSCAR, POTCAR, KPOINTS | Opt: CHGCAR, WAVECAR",
    description:
      "Single-directory VASP run with HDF5 output parsing and standard post-processing.",
  },
  vtst_neb: {
    label: "VTST NEB",
    required: VTST_MODE_CONFIG.pre_relaxed.required,
    optional: VTST_MODE_CONFIG.pre_relaxed.optional,
    outputs: VTST_SHARED_OUTPUTS,
    dropTitle: "Drop VTST NEB inputs here",
    dropHint: VTST_MODE_CONFIG.pre_relaxed.dropHint,
    description: VTST_MODE_CONFIG.pre_relaxed.description,
  },
  wannier_scf: {
    label: "Wannier SCF",
    required: ["INCAR", "POSCAR", "POTCAR", "KPOINTS"],
    optional: [],
    outputs: [
      "vasprun.xml",
      "vasp.out",
      "OUTCAR",
      "vaspout.h5",
      "WAVECAR",
      "CHGCAR",
      "CONTCAR",
      "OSZICAR",
      "EIGENVAL",
      "DOSCAR",
    ],
    dropTitle: "Drop Wannier SCF inputs here",
    dropHint: "Req: INCAR, POSCAR, POTCAR, KPOINTS",
    description:
      "Run a first SCF with the HDF5 VASP build. This stage should generate WAVECAR and, optionally, CHGCAR for the later Wannier step.",
  },
  wannier_post: {
    label: "Wannier post",
    required: ["INCAR"],
    optional: [],
    outputs: [
      "vasprun.xml",
      "vasp.out",
      "OUTCAR",
      "wannier90.win",
      "wannier90.mmn",
      "wannier90.amn",
      "wannier90.eig",
      "wannier90.nnkp",
      "wannier90.wout",
      "wannier90.chk",
      "wannier90_hr.dat",
      "wannier90_r.dat",
      "wannier90_tb.dat",
      "wannier90_centres.xyz",
      "wannier_metrics.json",
      "wannier_centers.xyz",
      "hamiltonian.json",
      "hopping_graph.json",
      "plots/wannier_centers_overlay.png",
      "plots/wf_overview.png",
      "plots/hopping_vs_distance.png",
      "plots/hopping_pair_heatmap.png",
      "plots/hopping_graph.png",
      "plots/hopping_truncation.png",
    ],
    dropTitle: "Drop Wannier post INCAR here",
    dropHint: "Req: new post-processing INCAR | Source SCF job required below",
    description:
      "Copies POSCAR, POTCAR, KPOINTS, WAVECAR, and optional CHGCAR from a successful Wannier SCF job, then runs plain VASP and wannier90.x.",
  },
  wannier_postw90: {
    label: "Wannier postw90",
    required: [],
    optional: [],
    outputs: [
      "postw90.out",
      "postw90_metrics.json",
      "wannier90.win",
      "wannier90.chk",
      "wannier90_hr.dat",
      "wannier90_r.dat",
      "wannier90_tb.dat",
      "wannier90.bxsf",
      "wannier90.wpout",
      "plots/postw90_band.png",
      "plots/postw90_dos.png",
      "plots/postw90_ahc.png",
      "plots/postw90_seebeck.png",
      "plots/postw90_elcond.png",
      "plots/postw90_boltzdos.png",
    ],
    dropTitle: "postw90 derived job",
    dropHint: "Created from a successful Wannier post run",
    description:
      "Runs postw90.x on top of an existing Wannier model without uploading new files.",
  },
};
const getVaspModeConfig = (runMode, vtstMode = "pre_relaxed") => {
  if (runMode === "vtst_neb") {
    return {
      label: "VTST NEB",
      ...getVtstModeConfig(vtstMode),
    };
  }
  if (runMode === "wannier") return VASP_MODE_CONFIG.wannier_post;
  return VASP_MODE_CONFIG[runMode] || VASP_MODE_CONFIG.standard;
};

const POSTW90_MODULE_CONFIG = {
  band_interp: {
    label: "Band interpolation",
    description: "Auto-generate a SeeK-path line path and run interpolated bands.",
    fields: [
      { key: "bands_num_points", label: "Points / segment", type: "number", step: 1, defaultValue: 80 },
    ],
  },
  dos: {
    label: "DOS",
    description: "Interpolated total DOS on a dense k mesh.",
    fields: [
      { key: "dos_kmesh", label: "DOS k-mesh", type: "number", step: 1, defaultValue: 24 },
      { key: "dos_energy_min", label: "E min (eV)", type: "number", step: 0.1, defaultValue: -10 },
      { key: "dos_energy_max", label: "E max (eV)", type: "number", step: 0.1, defaultValue: 10 },
      { key: "dos_energy_step", label: "E step (eV)", type: "number", step: 0.01, defaultValue: 0.02 },
    ],
  },
  berry_ahc: {
    label: "Berry / AHC",
    description: "Run Berry-curvature driven anomalous Hall conductivity scans.",
    fields: [
      { key: "berry_kmesh", label: "Berry k-mesh", type: "number", step: 1, defaultValue: 24 },
      { key: "fermi_energy_min", label: "mu min (eV)", type: "number", step: 0.1, defaultValue: -1.0 },
      { key: "fermi_energy_max", label: "mu max (eV)", type: "number", step: 0.1, defaultValue: 1.0 },
      { key: "fermi_energy_step", label: "mu step (eV)", type: "number", step: 0.01, defaultValue: 0.02 },
    ],
  },
  fermi_surface: {
    label: "Fermi surface",
    description:
      "Run wannier90.x in restart=plot mode and export the interpolated Fermi-surface mesh.",
    fields: [
      { key: "fermi_surface_num_points", label: "Grid points", type: "number", step: 1, defaultValue: 80 },
      {
        key: "fermi_energy",
        label: "Fermi energy override (eV)",
        type: "number",
        step: 0.001,
        defaultValue: "",
      },
    ],
  },
  boltzwann: {
    label: "BoltzWann transport",
    description: "Compute conductivity and Seebeck curves in the relaxation-time approximation.",
    fields: [
      { key: "boltz_kmesh", label: "Boltz k-mesh", type: "number", step: 1, defaultValue: 28 },
      { key: "boltz_mu_min", label: "mu min (eV)", type: "number", step: 0.1, defaultValue: -1.0 },
      { key: "boltz_mu_max", label: "mu max (eV)", type: "number", step: 0.1, defaultValue: 1.0 },
      { key: "boltz_mu_step", label: "mu step (eV)", type: "number", step: 0.01, defaultValue: 0.05 },
      { key: "boltz_temp_min", label: "T min (K)", type: "number", step: 10, defaultValue: 100 },
      { key: "boltz_temp_max", label: "T max (K)", type: "number", step: 10, defaultValue: 800 },
      { key: "boltz_temp_step", label: "T step (K)", type: "number", step: 10, defaultValue: 100 },
      { key: "boltz_relax_time", label: "tau (fs)", type: "number", step: 0.1, defaultValue: 10.0 },
    ],
  },
};

const ANALYSIS_MODELS = [
  { value: "qwen3.6-plus", label: "Qwen3.6-Plus" },
  { value: "deepseek-v3.2", label: "DeepSeek-V3.2" },
  { value: "kimi-k2.5", label: "Kimi-K2.5" },
  { value: "glm-5", label: "GLM-5" },
  { value: "MiniMax-M2.5", label: "MiniMax-M2.5" },
];

const VASP_ANALYSIS_MODELS = ANALYSIS_MODELS;

const MODEL_CONFIG = {
  mattergen_base: {
    label: "mattergen_base",
    group: "Unconditioned",
    description: "Base generator without property conditioning.",
    fields: [],
    guidance: false,
  },
  mp_20_base: {
    label: "mp_20_base",
    group: "Unconditioned",
    description: "MP-20 base model without property conditioning.",
    fields: [],
    guidance: false,
  },
  chemical_system: {
    label: "chemical_system",
    group: "Conditioned",
    description: "Generate within a specific chemical system.",
    fields: [
      {
        key: "chemical_system",
        label: "Chemical system",
        type: "text",
        placeholder: "Li-O",
      },
    ],
    guidance: true,
  },
  space_group: {
    label: "space_group",
    group: "Conditioned",
    description: "Generate within a specific space group (1-230).",
    fields: [
      {
        key: "space_group",
        label: "Space group",
        type: "number",
        step: 1,
        placeholder: "225",
        cast: "int",
      },
    ],
    guidance: true,
  },
  dft_mag_density: {
    label: "dft_mag_density",
    group: "Conditioned",
    description: "Target DFT magnetic density.",
    fields: [
      {
        key: "dft_mag_density",
        label: "Target mag density",
        type: "number",
        step: 0.01,
        placeholder: "0.15",
      },
    ],
    guidance: true,
  },
  dft_band_gap: {
    label: "dft_band_gap",
    group: "Conditioned",
    description: "Target DFT band gap in eV.",
    fields: [
      {
        key: "dft_band_gap",
        label: "Target band gap (eV)",
        type: "number",
        step: 0.01,
        placeholder: "1.5",
      },
    ],
    guidance: true,
  },
  ml_bulk_modulus: {
    label: "ml_bulk_modulus",
    group: "Conditioned",
    description: "Target ML bulk modulus in GPa.",
    fields: [
      {
        key: "ml_bulk_modulus",
        label: "Bulk modulus (GPa)",
        type: "number",
        step: 1,
        placeholder: "200",
      },
    ],
    guidance: true,
  },
  dft_mag_density_hhi_score: {
    label: "dft_mag_density_hhi_score",
    group: "Multi-condition",
    description: "Joint target for magnetic density and HHI score.",
    fields: [
      {
        key: "dft_mag_density",
        label: "Target mag density",
        type: "number",
        step: 0.01,
        placeholder: "0.15",
      },
      {
        key: "hhi_score",
        label: "HHI score",
        type: "number",
        step: 0.01,
        placeholder: "0.8",
      },
    ],
    guidance: true,
  },
  chemical_system_energy_above_hull: {
    label: "chemical_system_energy_above_hull",
    group: "Multi-condition",
    description: "Chemical system with energy above hull target.",
    fields: [
      {
        key: "chemical_system",
        label: "Chemical system",
        type: "text",
        placeholder: "Li-O",
      },
      {
        key: "energy_above_hull",
        label: "Energy above hull",
        type: "number",
        step: 0.01,
        placeholder: "0.05",
      },
    ],
    guidance: true,
  },
};

const STATUS_TONE = {
  SUCCESS: "status--success",
  FAILURE: "status--danger",
  REVOKED: "status--muted",
  STARTED: "status--warn",
  PENDING: "status--muted",
  RETRY: "status--warn",
};

const formatDateTime = (value) => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

const buildPayload = (modelName, batchSize, numBatches, properties, guidance) => {
  const config = MODEL_CONFIG[modelName];
  const payload = {
    model_name: modelName,
    batch_size: Number(batchSize) || 1,
    num_batches: Number(numBatches) || 1,
  };

  const props = {};
  config.fields.forEach((field) => {
    const rawValue = properties[field.key];
    if (rawValue === undefined || rawValue === null || rawValue === "") return;

    let parsed = rawValue;
    if (field.type === "number") {
      parsed = field.cast === "int" ? parseInt(rawValue, 10) : Number(rawValue);
      if (Number.isNaN(parsed)) return;
    }
    props[field.key] = parsed;
  });

  if (Object.keys(props).length > 0) {
    payload.properties_to_condition_on = props;
  }

  if (config.guidance && guidance !== "") {
    const g = Number(guidance);
    if (!Number.isNaN(g)) {
      payload.diffusion_guidance_factor = g;
    }
  }

  return payload;
};

const sortJobs = (items) =>
  [...items].sort((a, b) => {
    const aTime = new Date(a.created_at || 0).getTime();
    const bTime = new Date(b.created_at || 0).getTime();
    return bTime - aTime;
  });

const fileNameFromPath = (path) => (path ? path.split("/").pop() : null);

const normalizePath = (value) => (value ? value.replaceAll("\\", "/") : "");

const relativeArtifactPath = (path, rootDir) => {
  if (!path) return null;
  const normalizedPath = normalizePath(path);
  const normalizedRoot = normalizePath(rootDir);
  if (normalizedRoot && normalizedPath.startsWith(`${normalizedRoot}/`)) {
    return normalizedPath.slice(normalizedRoot.length + 1);
  }
  return normalizedPath.includes("/") ? normalizedPath.split("/").pop() : normalizedPath;
};

const formatMetricValue = (value, digits = 4) => {
  if (value === null || value === undefined || value === "") return "-";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return String(value);
  return numeric.toFixed(digits);
};

const formatBooleanMetric = (value) => {
  if (value === null || value === undefined) return "-";
  return value ? "Yes" : "No";
};

const getVaspWorkflowLabel = (runMode) => {
  if (runMode === "vtst_neb") return "VTST NEB";
  if (runMode === "wannier_scf") return "Wannier SCF";
  if (runMode === "wannier_postw90") return "Wannier postw90";
  if (runMode === "wannier_post" || runMode === "wannier") return "Wannier post";
  return "HDF5 standard";
};

const summarizeHdf5Qc = (metrics) => {
  const qc = metrics?.qc || {};
  const flags = Array.isArray(qc.flags) ? qc.flags : [];
  const counts = flags.reduce(
    (acc, flag) => {
      const severity = flag?.severity || "info";
      if (severity === "error") acc.error += 1;
      else if (severity === "warn") acc.warn += 1;
      else acc.info += 1;
      return acc;
    },
    { error: 0, warn: 0, info: 0 }
  );

  const maxForce = Number(qc.max_force_eVA);
  const forceThreshold = Number(qc.force_threshold_eVA);
  const maxStress = Number(qc.max_stress_kbar);
  const stressThreshold = Number(qc.stress_threshold_kbar);

  const forceExceeded =
    Number.isFinite(maxForce) &&
    Number.isFinite(forceThreshold) &&
    maxForce > forceThreshold;
  const stressExceeded =
    Number.isFinite(maxStress) &&
    Number.isFinite(stressThreshold) &&
    maxStress > stressThreshold;

  let level = "muted";
  let label = "Unknown";

  if (qc.finished_cleanly === false || counts.error > 0) {
    level = "danger";
    label = "Fail";
  } else if (
    qc.finished_cleanly === true ||
    qc.electronic_converged === true ||
    qc.ionic_converged === true ||
    flags.length > 0 ||
    qc.electronic_converged === false
  ) {
    level =
      qc.electronic_converged === false ||
      qc.ionic_converged === false ||
      counts.warn > 0 ||
      forceExceeded ||
      stressExceeded
        ? "warn"
        : "success";
    label = level === "success" ? "Pass" : "Warn";
  }

  const summaryParts = [];
  if (qc.finished_cleanly === false) summaryParts.push("job did not finish cleanly");
  if (qc.electronic_converged === false) summaryParts.push("electronic convergence failed");
  if (qc.ionic_converged === false) summaryParts.push("ionic convergence incomplete");
  if (forceExceeded) summaryParts.push("force exceeds threshold");
  if (stressExceeded) summaryParts.push("stress exceeds threshold");
  if (counts.error > 0) summaryParts.push(`${counts.error} error flag${counts.error > 1 ? "s" : ""}`);
  if (counts.warn > 0) summaryParts.push(`${counts.warn} warning flag${counts.warn > 1 ? "s" : ""}`);
  if (summaryParts.length === 0 && level === "success") {
    summaryParts.push("No blocking QC issues detected");
  }
  if (summaryParts.length === 0 && level === "muted") {
    summaryParts.push("QC summary is not available yet");
  }

  return {
    level,
    label,
    counts,
    forceExceeded,
    stressExceeded,
    summary: summaryParts.join(" | "),
  };
};

const JOBS_PREVIEW_LIMIT = 11;
const VASP_JOBS_PREVIEW_LIMIT = 13;
const MATTERGEN_STRUCTURE_PREVIEW_LIMIT = 8;
const WANNIER_FUNCTION_PREVIEW_LIMIT = 8;
const WANNIER_PLOT_PREVIEW_LIMIT = 8;
const REASONING_MARK = "### Reasoning";
const ANSWER_MARK = "### Answer";
const TERMINAL_JOB_STATES = new Set(["SUCCESS", "FAILURE", "REVOKED"]);

const describeArtifact = (artifact) => {
  const normalized = normalizePath(artifact || "");
  const parts = normalized.split("/").filter(Boolean);
  const file = parts.pop() || normalized || "-";
  let group = parts.join(" / ");

  if (!group) {
    if (file.startsWith("endpoint_initial_")) group = "endpoint initial";
    else if (file.startsWith("endpoint_final_")) group = "endpoint final";
    else if (
      file.endsWith(".h5") ||
      file === "vasprun.xml" ||
      file === "OUTCAR" ||
      file === "vasp.out"
    ) {
      group = "root output";
    }
  }

  return { file, group };
};

const buildVaspArtifactHref = (apiBase, jobId, relPath) =>
  `${apiBase}/api/vasp/jobs/${jobId}/artifacts/${encodeURIComponent(relPath)}`;

const createPostw90Params = (module) =>
  Object.fromEntries(
    (POSTW90_MODULE_CONFIG[module]?.fields || []).map((field) => [
      field.key,
      String(field.defaultValue ?? ""),
    ])
  );

const pickAllowedModel = (value, options, fallback) =>
  options.some((item) => item.value === value) ? value : fallback;

const splitReasoning = (text) => {
  if (!text) return { reasoning: "", answer: "" };
  const reasoningIndex = text.indexOf(REASONING_MARK);
  if (reasoningIndex === -1) {
    return { reasoning: "", answer: text.trimStart() };
  }
  const afterReasoning = text.slice(reasoningIndex + REASONING_MARK.length);
  const answerIndex = afterReasoning.indexOf(ANSWER_MARK);
  if (answerIndex === -1) {
    return { reasoning: afterReasoning.trimStart(), answer: "" };
  }
  const reasoning = afterReasoning.slice(0, answerIndex).trimStart();
  const answer = afterReasoning
    .slice(answerIndex + ANSWER_MARK.length)
    .trimStart();
  return { reasoning, answer };
};

export default function App() {
  const [modelName, setModelName] = useState("mattergen_base");
  const [batchSize, setBatchSize] = useState("1");
  const [numBatches, setNumBatches] = useState("1");
  const [properties, setProperties] = useState({});
  const [guidance, setGuidance] = useState("2.0");

  const [jobs, setJobs] = useState([]);
  const [activeJobId, setActiveJobId] = useState(null);
  const [activeJob, setActiveJob] = useState(null);
  const [logLines, setLogLines] = useState([]);
  const [logStatus, setLogStatus] = useState("idle");
  const [analysisText, setAnalysisText] = useState("");
  const [analysisStatus, setAnalysisStatus] = useState("idle");
  const [analysisError, setAnalysisError] = useState(null);
  const [analysisModel, setAnalysisModel] = useState("qwen3.6-plus");
  const [metricsData, setMetricsData] = useState(null);
  const [metricsStatus, setMetricsStatus] = useState("idle");
  const [metricsError, setMetricsError] = useState(null);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatStatus, setChatStatus] = useState("idle");
  const [chatError, setChatError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [lastError, setLastError] = useState(null);
  const [showAllJobs, setShowAllJobs] = useState(false);
  const [showAllMattergenStructures, setShowAllMattergenStructures] =
    useState(false);
  const [activeMode, setActiveMode] = useState("mattergen");

  const [vaspFiles, setVaspFiles] = useState({});
  const [vaspJobName, setVaspJobName] = useState("");
  const [vaspRunMode, setVaspRunMode] = useState("standard");
  const [vaspVtstMode, setVaspVtstMode] = useState("pre_relaxed");
  const [vaspSourceJobId, setVaspSourceJobId] = useState("");
  const [vaspWannierEnableLwriteUnk, setVaspWannierEnableLwriteUnk] =
    useState(false);
  const [vaspWannierEnablePlot, setVaspWannierEnablePlot] = useState(false);
  const [vaspNproc, setVaspNproc] = useState(String(VASP_DEFAULT_NPROC));
  const [vaspEndpointNproc, setVaspEndpointNproc] = useState(
    String(VASP_DEFAULT_NPROC)
  );
  const [vaspExec, setVaspExec] = useState("vasp_std");
  const [vaspJobs, setVaspJobs] = useState([]);
  const [showAllVaspJobs, setShowAllVaspJobs] = useState(false);
  const [activeVaspJobId, setActiveVaspJobId] = useState(null);
  const [activeVaspJob, setActiveVaspJob] = useState(null);
  const [vaspLogLines, setVaspLogLines] = useState([]);
  const [vaspLogStatus, setVaspLogStatus] = useState("idle");
  const [vaspSubmitting, setVaspSubmitting] = useState(false);
  const [vaspError, setVaspError] = useState(null);
  const [vaspRefreshing, setVaspRefreshing] = useState(false);
  const [vaspFileError, setVaspFileError] = useState(null);
  const [vaspDropActive, setVaspDropActive] = useState(false);
  const [vaspMetricsData, setVaspMetricsData] = useState(null);
  const [vaspMetricsStatus, setVaspMetricsStatus] = useState("idle");
  const [vaspMetricsError, setVaspMetricsError] = useState(null);
  const [vaspAnalysisText, setVaspAnalysisText] = useState("");
  const [vaspAnalysisStatus, setVaspAnalysisStatus] = useState("idle");
  const [vaspAnalysisError, setVaspAnalysisError] = useState(null);
  const [vaspAnalysisModel, setVaspAnalysisModel] = useState("qwen3.6-plus");
  const [vaspChatMessages, setVaspChatMessages] = useState([]);
  const [vaspChatInput, setVaspChatInput] = useState("");
  const [vaspChatStatus, setVaspChatStatus] = useState("idle");
  const [vaspChatError, setVaspChatError] = useState(null);
  const [vaspStopping, setVaspStopping] = useState(false);
  const [showAllWannierFunctions, setShowAllWannierFunctions] = useState(false);
  const [showAllWannierPlots, setShowAllWannierPlots] = useState(false);
  const [wannierDetailsData, setWannierDetailsData] = useState(null);
  const [wannierDetailsStatus, setWannierDetailsStatus] = useState("idle");
  const [wannierDetailsError, setWannierDetailsError] = useState(null);
  const [postw90Module, setPostw90Module] = useState("band_interp");
  const [postw90Params, setPostw90Params] = useState(() =>
    createPostw90Params("band_interp")
  );
  const [postw90Submitting, setPostw90Submitting] = useState(false);
  const [postw90Error, setPostw90Error] = useState(null);

  useEffect(() => {
    document.body.dataset.mode = activeMode;
    return () => {
      delete document.body.dataset.mode;
    };
  }, [activeMode]);

  useEffect(() => {
    setVaspFileError(null);
    const modeConfig = getVaspModeConfig(vaspRunMode, vaspVtstMode);
    const allowed = new Set([
      ...modeConfig.required,
      ...modeConfig.optional,
    ]);
    setVaspFiles((prev) =>
      Object.fromEntries(
        Object.entries(prev).filter(([name]) => allowed.has(name))
      )
    );
  }, [vaspRunMode, vaspVtstMode]);

  useEffect(() => {
    setPostw90Params(createPostw90Params(postw90Module));
    setPostw90Error(null);
  }, [postw90Module]);

  const logBoxRef = useRef(null);
  const analysisBoxRef = useRef(null);
  const chatBoxRef = useRef(null);
  const vaspLogBoxRef = useRef(null);
  const vaspAnalysisBoxRef = useRef(null);
  const vaspChatBoxRef = useRef(null);
  const analysisAutoScrollRef = useRef(true);
  const chatAutoScrollRef = useRef(true);
  const vaspAnalysisAutoScrollRef = useRef(true);
  const vaspChatAutoScrollRef = useRef(true);

  const config = MODEL_CONFIG[modelName];
  const canAnalyze = activeJob?.status === "SUCCESS";
  const canDownloadArtifacts = activeJob?.status === "SUCCESS";
  const canChat = canAnalyze && analysisStatus === "ready";
  const isVaspMode = activeMode === "vasp";
  const headerCopy = isVaspMode
    ? {
        eyebrow: "Unified workspace for materials computation",
        workflowTitle: "VASP Studio",
        workflowNote: "First-principles workflows, post-processing, and property intelligence",
        subhead:
          "Run HDF5, VTST NEB, Wannier, and postw90 workflows in one place, with live logs, structured metrics, and AI-guided interpretation.",
      }
    : {
        eyebrow: "Unified workspace for generative materials design",
        workflowTitle: "MatterGen Studio",
        workflowNote: "Conditioned crystal generation, feature extraction, and rapid triage",
        subhead:
          "Launch conditioned generation, inspect post-processed structures, and move from raw samples to simulation-ready insights without leaving the platform.",
      };
  const vaspModeConfig = getVaspModeConfig(vaspRunMode, vaspVtstMode);
  const activeVaspRunMode = activeVaspJob?.meta?.run_mode || vaspRunMode;
  const activeVaspVtstMode = activeVaspJob?.meta?.vtst_mode || "pre_relaxed";
  const activeVaspModeConfig = getVaspModeConfig(activeVaspRunMode, activeVaspVtstMode);
  const vaspRequiredFiles = vaspModeConfig.required;
  const vaspOptionalFiles = vaspModeConfig.optional;
  const vaspOutputs =
    Array.isArray(activeVaspJob?.meta?.available_output_files)
      ? activeVaspJob.meta.available_output_files
      : activeVaspJob?.meta?.output_files?.length > 0
      ? activeVaspJob.meta.output_files
      : activeVaspModeConfig.outputs;
  const vaspMissingRequired = vaspRequiredFiles.filter(
    (name) => !vaspFiles[name]
  );
  const vaspCanSubmit = vaspMissingRequired.length === 0 && !vaspSubmitting;
  const vaspCanDownload =
    activeVaspJob?.status === "SUCCESS" || activeVaspJob?.status === "REVOKED";
  const isActiveVtstJob = activeVaspJob?.meta?.run_mode === "vtst_neb";
  const isActiveWannierScfJob = activeVaspJob?.meta?.run_mode === "wannier_scf";
  const isActivePostw90Job = activeVaspJob?.meta?.run_mode === "wannier_postw90";
  const isActiveWannierPostJob = ["wannier", "wannier_post"].includes(
    activeVaspJob?.meta?.run_mode || ""
  );
  const activeWannierVisualizationOptions =
    activeVaspJob?.meta?.wannier_visualization_options || {};
  const isActiveWannierJob =
    isActiveWannierScfJob || isActiveWannierPostJob || isActivePostw90Job;
  const vaspSupportsMetrics = !isActiveWannierScfJob;
  const vaspSupportsAi = !isActiveWannierScfJob;
  const canLaunchPostw90 =
    isActiveWannierPostJob &&
    activeVaspJob?.status === "SUCCESS" &&
    !postw90Submitting;
  const vaspStopRequested =
    Boolean(activeVaspJob?.meta?.stop_requested) &&
    !TERMINAL_JOB_STATES.has(activeVaspJob?.status || "");
  const canStopVasp =
    Boolean(activeVaspJob?.job_id) &&
    !TERMINAL_JOB_STATES.has(activeVaspJob?.status || "") &&
    !vaspStopRequested &&
    !vaspStopping;
  const canAnalyzeVasp =
    activeVaspJob?.status === "SUCCESS" &&
    vaspSupportsAi &&
    vaspMetricsStatus === "ready";
  const canChatVasp = canAnalyzeVasp && vaspAnalysisStatus === "ready";
  const wannierScfSourceJobs = useMemo(
    () =>
      vaspJobs.filter(
        (job) =>
          job.status === "SUCCESS" &&
          ["wannier_scf", "wannier"].includes(job.meta?.run_mode || "")
      ),
    [vaspJobs]
  );
  const needsWannierSource = vaspRunMode === "wannier_post";
  const hasValidWannierSource =
    !needsWannierSource ||
    Boolean(wannierScfSourceJobs.find((job) => job.job_id === vaspSourceJobId));

  useEffect(() => {
    if (vaspRunMode !== "wannier_post") {
      setVaspSourceJobId("");
      return;
    }
    if (
      vaspSourceJobId &&
      wannierScfSourceJobs.some((job) => job.job_id === vaspSourceJobId)
    ) {
      return;
    }
    setVaspSourceJobId(wannierScfSourceJobs[0]?.job_id || "");
  }, [vaspRunMode, vaspSourceJobId, wannierScfSourceJobs]);

  useEffect(() => {
    setProperties((prev) => {
      const next = {};
      config.fields.forEach((field) => {
        next[field.key] = prev[field.key] ?? "";
      });
      return next;
    });
    if (!config.guidance) {
      setGuidance("");
    } else if (guidance === "") {
      setGuidance("2.0");
    }
  }, [modelName]);

  const payloadPreview = useMemo(
    () => buildPayload(modelName, batchSize, numBatches, properties, guidance),
    [modelName, batchSize, numBatches, properties, guidance]
  );

  const loadJobs = async () => {
    setRefreshing(true);
    try {
      const res = await fetch(`${API_BASE}/api/jobs`);
      if (!res.ok) {
        throw new Error(`Failed to load jobs (${res.status})`);
      }
      const data = await res.json();
      const sorted = sortJobs(data);
      setJobs(sorted);
      setLastError(null);
      if (sorted.length > 0) {
        setActiveJobId((prev) => prev ?? sorted[0].job_id);
      }
    } catch (err) {
      setLastError(err.message || "Failed to load jobs.");
    } finally {
      setRefreshing(false);
    }
  };

  const loadVaspJobs = async () => {
    setVaspRefreshing(true);
    try {
      const res = await fetch(`${API_BASE}/api/vasp/jobs`);
      if (!res.ok) {
        throw new Error(`Failed to load VASP jobs (${res.status})`);
      }
      const data = await res.json();
      const sorted = sortJobs(data);
      setVaspJobs(sorted);
      setVaspError(null);
      if (sorted.length > 0) {
        setActiveVaspJobId((prev) => prev ?? sorted[0].job_id);
      }
    } catch (err) {
      setVaspError(err.message || "Failed to load VASP jobs.");
    } finally {
      setVaspRefreshing(false);
    }
  };

  const loadVaspMetrics = async (jobId) => {
    if (!jobId) return;
    setVaspMetricsError(null);
    setVaspMetricsStatus("loading");
    try {
      const res = await fetch(`${API_BASE}/api/vasp/jobs/${jobId}/metrics`);
      if (res.status === 400) {
        setVaspMetricsData(null);
        setVaspMetricsStatus("unsupported");
        return;
      }
      if (res.status === 404) {
        setVaspMetricsData(null);
        setVaspMetricsStatus("missing");
        return;
      }
      if (!res.ok) {
        throw new Error(`Failed to load VASP metrics (${res.status})`);
      }
      const data = await res.json();
      setVaspMetricsData(data);
      setVaspMetricsStatus("ready");
    } catch (err) {
      setVaspMetricsStatus("error");
      setVaspMetricsError(err.message || "Failed to load VASP metrics.");
    }
  };

  const loadWannierDetails = async (jobId, relPath) => {
    if (!jobId || !relPath) return null;
    if (wannierDetailsStatus === "loading") return null;
    setWannierDetailsError(null);
    setWannierDetailsStatus("loading");
    try {
      const res = await fetch(
        `${API_BASE}/api/vasp/jobs/${jobId}/artifacts/${encodeURIComponent(relPath)}`
      );
      if (!res.ok) {
        throw new Error(`Failed to load Wannier details (${res.status})`);
      }
      const data = await res.json();
      setWannierDetailsData(data);
      setWannierDetailsStatus("ready");
      return data;
    } catch (err) {
      setWannierDetailsStatus("error");
      setWannierDetailsError(err.message || "Failed to load Wannier details.");
      return null;
    }
  };

  const toggleWannierFunctionTable = async () => {
    if (showAllWannierFunctions) {
      setShowAllWannierFunctions(false);
      return;
    }
    if (wannierFunctions.length > 0) {
      setShowAllWannierFunctions(true);
      return;
    }
    if (wannierDetailsRelPath && activeVaspJobId) {
      const data = await loadWannierDetails(activeVaspJobId, wannierDetailsRelPath);
      if (data?.wannier_functions?.length) {
        setShowAllWannierFunctions(true);
        return;
      }
    }
    setShowAllWannierFunctions(true);
  };

  const loadVaspAnalysis = async (jobId) => {
    if (!jobId) return;
    setVaspAnalysisError(null);
    setVaspAnalysisStatus("loading");
    try {
      const res = await fetch(`${API_BASE}/api/vasp/jobs/${jobId}/analysis`);
      if (res.status === 400) {
        setVaspAnalysisText("");
        setVaspAnalysisStatus("unsupported");
        return;
      }
      if (res.status === 404) {
        setVaspAnalysisText("");
        setVaspAnalysisStatus("idle");
        return;
      }
      if (!res.ok) {
        throw new Error(`Failed to load VASP analysis (${res.status})`);
      }
      const data = await res.json();
      setVaspAnalysisText(data.analysis || "");
      setVaspAnalysisStatus(data.analysis ? "ready" : "idle");
      if (data.analysis_model) {
        setVaspAnalysisModel(
          pickAllowedModel(
            data.analysis_model,
            VASP_ANALYSIS_MODELS,
            "qwen3.6-plus"
          )
        );
      }
    } catch (err) {
      setVaspAnalysisStatus("error");
      setVaspAnalysisError(err.message || "Failed to load VASP analysis.");
    }
  };

  const loadVaspChat = async (jobId) => {
    if (!jobId) return;
    setVaspChatError(null);
    setVaspChatStatus("loading");
    try {
      const res = await fetch(`${API_BASE}/api/vasp/jobs/${jobId}/chat`);
      if (res.status === 400) {
        setVaspChatMessages([]);
        setVaspChatStatus("unsupported");
        return;
      }
      if (res.status === 404) {
        setVaspChatMessages([]);
        setVaspChatStatus("idle");
        return;
      }
      if (!res.ok) {
        throw new Error(`Failed to load VASP chat (${res.status})`);
      }
      const data = await res.json();
      setVaspChatMessages(data.messages || []);
      setVaspChatStatus("ready");
    } catch (err) {
      setVaspChatStatus("error");
      setVaspChatError(err.message || "Failed to load VASP chat.");
    }
  };

  const loadAnalysis = async (jobId) => {
    if (!jobId) return;
    setAnalysisError(null);
    setAnalysisStatus("loading");
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}/analysis`);
      if (res.status === 404) {
        setAnalysisText("");
        setAnalysisStatus("idle");
        return;
      }
      if (!res.ok) {
        throw new Error(`Failed to load analysis (${res.status})`);
      }
      const data = await res.json();
      setAnalysisText(data.analysis || "");
      setAnalysisStatus(data.analysis ? "ready" : "idle");
      if (data.analysis_model) {
        setAnalysisModel(
          pickAllowedModel(data.analysis_model, ANALYSIS_MODELS, "qwen3.6-plus")
        );
      }
    } catch (err) {
      setAnalysisStatus("error");
      setAnalysisError(err.message || "Failed to load analysis.");
    }
  };

  const loadMetrics = async (jobId) => {
    if (!jobId) return;
    setMetricsError(null);
    setMetricsStatus("loading");
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}/metrics`);
      if (res.status === 404) {
        setMetricsData(null);
        setMetricsStatus("missing");
        return;
      }
      if (!res.ok) {
        throw new Error(`Failed to load metrics (${res.status})`);
      }
      const data = await res.json();
      setMetricsData(data);
      setMetricsStatus("ready");
    } catch (err) {
      setMetricsStatus("error");
      setMetricsError(err.message || "Failed to load metrics.");
    }
  };

  const loadChat = async (jobId) => {
    if (!jobId) return;
    setChatError(null);
    setChatStatus("loading");
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}/chat`);
      if (res.status === 404) {
        setChatMessages([]);
        setChatStatus("idle");
        return;
      }
      if (!res.ok) {
        throw new Error(`Failed to load chat (${res.status})`);
      }
      const data = await res.json();
      setChatMessages(data.messages || []);
      setChatStatus("ready");
    } catch (err) {
      setChatStatus("error");
      setChatError(err.message || "Failed to load chat.");
    }
  };

  const handleVaspFileList = (fileList) => {
    if (!fileList || fileList.length === 0) return;
    setVaspFileError(null);
    const allowed = new Set([...vaspRequiredFiles, ...vaspOptionalFiles]);
    setVaspFiles((prev) => {
      const next = { ...prev };
      Array.from(fileList).forEach((file) => {
        const name = file.name.trim();
        if (!allowed.has(name)) {
          setVaspFileError(
            `Unsupported file: ${name}. Allowed: ${[...allowed].join(", ")}`
          );
          return;
        }
        next[name] = file;
      });
      return next;
    });
  };

  const handleVaspDrop = (event) => {
    event.preventDefault();
    setVaspDropActive(false);
    handleVaspFileList(event.dataTransfer?.files);
  };

  const handleVaspDragOver = (event) => {
    event.preventDefault();
    if (!vaspDropActive) {
      setVaspDropActive(true);
    }
  };

  const handleVaspDragLeave = () => {
    setVaspDropActive(false);
  };

  const removeVaspFile = (name) => {
    setVaspFiles((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
  };

  const submitVaspJob = async (event) => {
    event.preventDefault();
    setVaspSubmitting(true);
    setVaspError(null);
    setVaspFileError(null);
    try {
      const missing = vaspRequiredFiles.filter((name) => !vaspFiles[name]);
      if (missing.length > 0) {
        throw new Error(`Missing required files: ${missing.join(", ")}`);
      }
      if (needsWannierSource && !hasValidWannierSource) {
        throw new Error("Select a successful Wannier SCF job first.");
      }
      const formData = new FormData();
      formData.append("job_name", vaspJobName.trim());
      formData.append("run_mode", vaspRunMode);
      if (vaspRunMode === "vtst_neb") {
        formData.append("vtst_mode", vaspVtstMode);
      }
      formData.append("nproc", vaspNproc || String(VASP_DEFAULT_NPROC));
      formData.append(
        "endpoint_nproc",
        vaspEndpointNproc || String(VASP_DEFAULT_NPROC)
      );
      if (needsWannierSource) {
        formData.append("source_job_id", vaspSourceJobId);
        formData.append(
          "wannier_enable_lwrite_unk",
          String(vaspWannierEnableLwriteUnk)
        );
        formData.append("wannier_enable_plot", String(vaspWannierEnablePlot));
      }
      formData.append("vasp_exec", vaspExec);
      const allowed = new Set([...vaspRequiredFiles, ...vaspOptionalFiles]);
      Object.values(vaspFiles).forEach((file) => {
        if (!allowed.has(file.name)) return;
        formData.append("files", file, file.name);
      });
      const res = await fetch(`${API_BASE}/api/vasp/jobs`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const message = await res.text();
        throw new Error(message || `Submit failed (${res.status})`);
      }
      const data = await res.json();
      setActiveVaspJobId(data.job_id);
      await loadVaspJobs();
    } catch (err) {
      setVaspError(err.message || "VASP submission failed.");
    } finally {
      setVaspSubmitting(false);
    }
  };

  const stopVaspJob = async () => {
    if (!activeVaspJobId || !canStopVasp) return;
    setVaspStopping(true);
    setVaspError(null);
    setActiveVaspJob((prev) =>
      prev
        ? {
            ...prev,
            meta: {
              ...prev.meta,
              stop_requested: true,
            },
          }
        : prev
    );
    setVaspJobs((prev) =>
      prev.map((job) =>
        job.job_id === activeVaspJobId
          ? {
              ...job,
              meta: {
                ...job.meta,
                stop_requested: true,
              },
            }
          : job
      )
    );
    try {
      const res = await fetch(`${API_BASE}/api/vasp/jobs/${activeVaspJobId}/stop`, {
        method: "POST",
      });
      if (!res.ok) {
        const message = await res.text();
        throw new Error(message || `Stop failed (${res.status})`);
      }
      await loadVaspJobs();
    } catch (err) {
      setActiveVaspJob((prev) =>
        prev
          ? {
              ...prev,
              meta: {
                ...prev.meta,
                stop_requested: false,
              },
            }
          : prev
      );
      setVaspJobs((prev) =>
        prev.map((job) =>
          job.job_id === activeVaspJobId
            ? {
                ...job,
                meta: {
                  ...job.meta,
                  stop_requested: false,
                },
              }
            : job
        )
      );
      setVaspError(err.message || "Failed to stop VASP job.");
    } finally {
      setVaspStopping(false);
    }
  };

  const submitPostw90Job = async () => {
    if (!activeVaspJobId || !canLaunchPostw90) return;
    setPostw90Submitting(true);
    setPostw90Error(null);
    try {
      const moduleConfig = POSTW90_MODULE_CONFIG[postw90Module];
      const params = {};
      (moduleConfig?.fields || []).forEach((field) => {
        const rawValue = postw90Params[field.key];
        if (rawValue === undefined || rawValue === null || rawValue === "") return;
        const parsedValue =
          field.type === "number" ? Number(rawValue) : rawValue;
        if (
          field.type === "number" &&
          Number.isNaN(parsedValue)
        ) {
          return;
        }
        params[field.key] = parsedValue;
      });

      const res = await fetch(
        `${API_BASE}/api/vasp/jobs/${activeVaspJobId}/postw90`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            module: postw90Module,
            job_name: `${POSTW90_MODULE_CONFIG[postw90Module]?.label || "postw90"} | ${
              activeVaspJob.meta?.job_name || activeVaspJobId.slice(0, 8)
            }`,
            nproc: Number(vaspNproc) || VASP_DEFAULT_NPROC,
            params,
          }),
        }
      );
      if (!res.ok) {
        const message = await res.text();
        throw new Error(message || `postw90 submit failed (${res.status})`);
      }
      const data = await res.json();
      setActiveVaspJobId(data.job_id);
      await loadVaspJobs();
    } catch (err) {
      setPostw90Error(err.message || "Failed to submit postw90 job.");
    } finally {
      setPostw90Submitting(false);
    }
  };

  const sendChat = async () => {
    if (!activeJobId) return;
    const trimmed = chatInput.trim();
    if (!trimmed) return;

    const userMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: trimmed,
    };
    const assistantId = `a-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const assistantMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
    };

    setChatMessages((prev) => [...prev, userMessage, assistantMessage]);
    setChatInput("");
    setChatStatus("loading");
    setChatError(null);

    try {
      const res = await fetch(
        `${API_BASE}/api/jobs/${activeJobId}/chat/stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: trimmed, model: analysisModel }),
        }
      );
      if (!res.ok) {
        const message = await res.text();
        throw new Error(message || `Chat failed (${res.status})`);
      }
      if (!res.body) {
        throw new Error("Streaming not supported by the server.");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (value) {
          const chunk = decoder.decode(value, { stream: !done });
          setChatMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? { ...msg, content: msg.content + chunk }
                : msg
            )
          );
        }
      }
      setChatStatus("ready");
    } catch (err) {
      setChatStatus("error");
      setChatError(err.message || "Chat failed.");
    }
  };

  const runAnalysis = async () => {
    if (!activeJobId) return;
    setAnalysisError(null);
    setAnalysisText("");
    setAnalysisStatus("loading");
    setChatMessages([]);
    setChatError(null);
    setChatStatus("idle");
    analysisAutoScrollRef.current = true;
    chatAutoScrollRef.current = true;
    try {
      const res = await fetch(
        `${API_BASE}/api/jobs/${activeJobId}/analysis/stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: analysisModel }),
        }
      );
      if (!res.ok) {
        const message = await res.text();
        throw new Error(message || `Analysis failed (${res.status})`);
      }
      if (!res.body) {
        throw new Error("Streaming not supported by the server.");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (value) {
          const chunk = decoder.decode(value, { stream: !done });
          setAnalysisText((prev) => prev + chunk);
        }
      }
      setAnalysisStatus("ready");
    } catch (err) {
      setAnalysisStatus("error");
      setAnalysisError(err.message || "Analysis failed.");
    }
  };

  const sendVaspChat = async () => {
    if (!activeVaspJobId) return;
    const trimmed = vaspChatInput.trim();
    if (!trimmed) return;

    const userMessage = {
      id: `vu-${Date.now()}`,
      role: "user",
      content: trimmed,
    };
    const assistantId = `va-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const assistantMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
    };

    setVaspChatMessages((prev) => [...prev, userMessage, assistantMessage]);
    setVaspChatInput("");
    setVaspChatStatus("loading");
    setVaspChatError(null);

    try {
      const res = await fetch(
        `${API_BASE}/api/vasp/jobs/${activeVaspJobId}/chat/stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: trimmed, model: vaspAnalysisModel }),
        }
      );
      if (!res.ok) {
        const message = await res.text();
        throw new Error(message || `VASP chat failed (${res.status})`);
      }
      if (!res.body) {
        throw new Error("Streaming not supported by the server.");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (value) {
          const chunk = decoder.decode(value, { stream: !done });
          setVaspChatMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? { ...msg, content: msg.content + chunk }
                : msg
            )
          );
        }
      }
      setVaspChatStatus("ready");
    } catch (err) {
      setVaspChatStatus("error");
      setVaspChatError(err.message || "VASP chat failed.");
    }
  };

  const runVaspAnalysis = async () => {
    if (!activeVaspJobId) return;
    setVaspAnalysisError(null);
    setVaspAnalysisText("");
    setVaspAnalysisStatus("loading");
    setVaspChatMessages([]);
    setVaspChatError(null);
    setVaspChatStatus("idle");
    vaspAnalysisAutoScrollRef.current = true;
    vaspChatAutoScrollRef.current = true;
    try {
      const res = await fetch(
        `${API_BASE}/api/vasp/jobs/${activeVaspJobId}/analysis/stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: vaspAnalysisModel }),
        }
      );
      if (!res.ok) {
        const message = await res.text();
        throw new Error(message || `VASP analysis failed (${res.status})`);
      }
      if (!res.body) {
        throw new Error("Streaming not supported by the server.");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (value) {
          const chunk = decoder.decode(value, { stream: !done });
          setVaspAnalysisText((prev) => prev + chunk);
        }
      }
      setVaspAnalysisStatus("ready");
    } catch (err) {
      setVaspAnalysisStatus("error");
      setVaspAnalysisError(err.message || "VASP analysis failed.");
    }
  };

  useEffect(() => {
    loadJobs();
    const timer = setInterval(loadJobs, 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (activeMode !== "vasp") return;
    loadVaspJobs();
    const timer = setInterval(loadVaspJobs, 5000);
    return () => clearInterval(timer);
  }, [activeMode]);

  useEffect(() => {
    if (!activeJobId) {
      setActiveJob(null);
      return;
    }
    const job = jobs.find((item) => item.job_id === activeJobId);
    if (job) {
      setActiveJob(job);
    } else {
      (async () => {
        try {
          const res = await fetch(`${API_BASE}/api/jobs/${activeJobId}`);
          if (res.ok) {
            const data = await res.json();
            setActiveJob(data);
          }
        } catch (err) {
          setLastError(err.message || "Failed to load job details.");
        }
      })();
    }
  }, [activeJobId, jobs]);

  useEffect(() => {
    if (!activeVaspJobId) {
      setActiveVaspJob(null);
      setVaspStopping(false);
      return;
    }
    const job = vaspJobs.find((item) => item.job_id === activeVaspJobId);
    if (job) {
      setActiveVaspJob(job);
    } else {
      (async () => {
        try {
          const res = await fetch(`${API_BASE}/api/vasp/jobs/${activeVaspJobId}`);
          if (res.ok) {
            const data = await res.json();
            setActiveVaspJob(data);
          }
        } catch (err) {
          setVaspError(err.message || "Failed to load VASP job details.");
        }
      })();
    }
  }, [activeVaspJobId, vaspJobs]);

  useEffect(() => {
    if (TERMINAL_JOB_STATES.has(activeVaspJob?.status || "")) {
      setVaspStopping(false);
    }
  }, [activeVaspJob?.status]);

  useEffect(() => {
    setShowAllWannierFunctions(false);
    setShowAllWannierPlots(false);
    setWannierDetailsData(null);
    setWannierDetailsStatus("idle");
    setWannierDetailsError(null);
    setPostw90Error(null);
  }, [activeVaspJobId]);

  useEffect(() => {
    setVaspMetricsData(null);
    setVaspMetricsError(null);
    setVaspMetricsStatus("idle");
    setVaspAnalysisText("");
    setVaspAnalysisError(null);
    setVaspAnalysisStatus("idle");
    setVaspChatMessages([]);
    setVaspChatError(null);
    setVaspChatStatus("idle");

    if (activeVaspJob?.status === "SUCCESS" && activeVaspJob?.meta?.run_mode === "wannier_scf") {
      setVaspMetricsStatus("unsupported");
      setVaspAnalysisStatus("unsupported");
      setVaspChatStatus("unsupported");
      return;
    }

    if (activeVaspJob?.status === "SUCCESS") {
      loadVaspAnalysis(activeVaspJob.job_id);
    }
  }, [activeVaspJob?.job_id, activeVaspJob?.meta?.run_mode, activeVaspJob?.status]);

  useEffect(() => {
    setAnalysisText("");
    setAnalysisError(null);
    setAnalysisStatus("idle");
    setMetricsData(null);
    setMetricsError(null);
    setMetricsStatus("idle");
    setShowAllMattergenStructures(false);
    setChatMessages([]);
    setChatError(null);
    setChatStatus("idle");
    if (activeJobId) {
      loadAnalysis(activeJobId);
    }
  }, [activeJobId]);

  useEffect(() => {
    if (analysisStatus === "ready" && activeJobId) {
      loadChat(activeJobId);
    }
  }, [analysisStatus, activeJobId]);

  useEffect(() => {
    if (vaspAnalysisStatus === "ready" && activeVaspJobId && vaspSupportsAi) {
      loadVaspChat(activeVaspJobId);
    }
  }, [vaspAnalysisStatus, activeVaspJobId, vaspSupportsAi]);

  useEffect(() => {
    if (!activeJob) return;
    if (activeJob.status === "SUCCESS" && metricsStatus === "idle") {
      loadMetrics(activeJob.job_id);
    }
  }, [activeJob, metricsStatus]);

  useEffect(() => {
    if (!activeVaspJob) return;
    if (
      activeVaspJob.status === "SUCCESS" &&
      activeVaspJob.meta?.run_mode !== "wannier_scf" &&
      vaspMetricsStatus === "idle"
    ) {
      loadVaspMetrics(activeVaspJob.job_id);
    }
  }, [activeVaspJob, vaspMetricsStatus]);

  useEffect(() => {
    if (!activeJobId) return;

    setLogLines([]);
    setLogStatus("connecting");

    const source = new EventSource(`${API_BASE}/api/jobs/${activeJobId}/logs`);

    source.onopen = () => setLogStatus("streaming");
    source.onmessage = (event) => {
      const line = event.data;
      setLogLines((prev) => {
        const next = [...prev, line];
        return next.length > 600 ? next.slice(next.length - 600) : next;
      });
    };
    source.onerror = () => {
      setLogStatus("closed");
      source.close();
    };

    return () => {
      source.close();
      setLogStatus("idle");
    };
  }, [activeJobId]);

  useEffect(() => {
    if (!activeVaspJobId || activeMode !== "vasp") return;

    setVaspLogLines([]);
    setVaspLogStatus("connecting");

    const source = new EventSource(
      `${API_BASE}/api/vasp/jobs/${activeVaspJobId}/logs`
    );

    source.onopen = () => setVaspLogStatus("streaming");
    source.onmessage = (event) => {
      const line = event.data;
      setVaspLogLines((prev) => {
        const next = [...prev, line];
        return next.length > 600 ? next.slice(next.length - 600) : next;
      });
    };
    source.onerror = () => {
      setVaspLogStatus("closed");
      source.close();
    };

    return () => {
      source.close();
      setVaspLogStatus("idle");
    };
  }, [activeVaspJobId, activeMode]);

  useEffect(() => {
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  }, [logLines]);

  useEffect(() => {
    if (vaspLogBoxRef.current) {
      vaspLogBoxRef.current.scrollTop = vaspLogBoxRef.current.scrollHeight;
    }
  }, [vaspLogLines]);

  useEffect(() => {
    if (vaspChatBoxRef.current && vaspChatAutoScrollRef.current) {
      vaspChatBoxRef.current.scrollTop = vaspChatBoxRef.current.scrollHeight;
    }
  }, [vaspChatMessages]);

  useEffect(() => {
    if (vaspAnalysisBoxRef.current && vaspAnalysisAutoScrollRef.current) {
      vaspAnalysisBoxRef.current.scrollTop = vaspAnalysisBoxRef.current.scrollHeight;
    }
  }, [vaspAnalysisText]);

  useEffect(() => {
    if (chatBoxRef.current && chatAutoScrollRef.current) {
      chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight;
    }
  }, [chatMessages]);

  useEffect(() => {
    if (analysisBoxRef.current && analysisAutoScrollRef.current) {
      analysisBoxRef.current.scrollTop = analysisBoxRef.current.scrollHeight;
    }
  }, [analysisText]);

  const handleChatScroll = () => {
    if (!chatBoxRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = chatBoxRef.current;
    chatAutoScrollRef.current =
      scrollTop + clientHeight >= scrollHeight - 40;
  };

  const handleAnalysisScroll = () => {
    if (!analysisBoxRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = analysisBoxRef.current;
    analysisAutoScrollRef.current =
      scrollTop + clientHeight >= scrollHeight - 40;
  };

  const handleVaspChatScroll = () => {
    if (!vaspChatBoxRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = vaspChatBoxRef.current;
    vaspChatAutoScrollRef.current =
      scrollTop + clientHeight >= scrollHeight - 40;
  };

  const handleVaspAnalysisScroll = () => {
    if (!vaspAnalysisBoxRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = vaspAnalysisBoxRef.current;
    vaspAnalysisAutoScrollRef.current =
      scrollTop + clientHeight >= scrollHeight - 40;
  };

  const submitJob = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setLastError(null);
    try {
      const payload = buildPayload(
        modelName,
        batchSize,
        numBatches,
        properties,
        guidance
      );
      const res = await fetch(`${API_BASE}/api/jobs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const message = await res.text();
        throw new Error(message || `Submit failed (${res.status})`);
      }
      const data = await res.json();
      setActiveJobId(data.job_id);
      await loadJobs();
    } catch (err) {
      setLastError(err.message || "Job submission failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const modelGroups = Object.values(MODEL_CONFIG).reduce((acc, model) => {
    if (!acc[model.group]) acc[model.group] = [];
    acc[model.group].push(model);
    return acc;
  }, {});

  const derivedArtifacts = useMemo(() => {
    if (!metricsData) return [];
    const items = [];
    const structures = metricsData.structures || [];

    if (structures.some((s) => s.features?.magpie)) {
      items.push({
        key: "magpie.csv",
        label: "magpie.csv (derived)",
        filename: "magpie.csv",
      });
    }

    structures.forEach((structure, index) => {
      const cifName = fileNameFromPath(structure.cif);
      if (cifName) {
        items.push({
          key: `cif-${index}`,
          label: `Structure ${index} CIF (derived)`,
          filename: cifName,
        });
      }
      const pngName = fileNameFromPath(structure.render?.png);
      if (pngName) {
        items.push({
          key: `png-${index}`,
          label: `Structure ${index} PNG (derived)`,
          filename: pngName,
        });
      }
      const npyName = fileNameFromPath(structure.soap_summary?.file_path);
      if (npyName) {
        items.push({
          key: `npy-${index}`,
          label: `Structure ${index} SOAP (derived)`,
          filename: npyName,
        });
      }
    });

    return items;
  }, [metricsData]);

  const pngGallery = useMemo(() => {
    if (!metricsData || !activeJobId) return [];
    const structures = metricsData.structures || [];
    return structures
      .map((structure, index) => {
        const pngName = fileNameFromPath(structure.render?.png);
        if (!pngName) return null;
        return {
          key: `gallery-${index}`,
          index,
          formula: structure.reduced_formula || `Structure ${index}`,
          src: `${API_BASE}/api/jobs/${activeJobId}/files/${encodeURIComponent(
            pngName
          )}`,
        };
      })
      .filter(Boolean);
  }, [metricsData, activeJobId]);

  const mattergenOverview = useMemo(() => {
    if (!metricsData) return null;

    const structures = Array.isArray(metricsData.structures)
      ? metricsData.structures
      : [];
    const jobWarnings = Array.isArray(metricsData.warnings)
      ? metricsData.warnings.filter(Boolean)
      : [];
    const groupCounts = new Map();
    const symmetryCounts = new Map();
    const issueFlags = [];

    let renderedCount = 0;
    let cifCount = 0;
    let soapCount = 0;
    let magpieCount = 0;
    let closeContactStructureCount = 0;
    let structureWarningCount = 0;
    let globalMinDistance = null;
    let closeContactThreshold = null;

    jobWarnings.forEach((warning, index) => {
      issueFlags.push({
        code: `JOB_WARNING_${index + 1}`,
        severity: "warn",
        evidence: warning,
      });
    });

    structures.forEach((structure, index) => {
      const formula = structure.reduced_formula || `Structure ${index}`;
      const dedupGroupId = structure.dedup?.group_id;
      if (dedupGroupId !== null && dedupGroupId !== undefined) {
        groupCounts.set(dedupGroupId, (groupCounts.get(dedupGroupId) || 0) + 1);
      }

      const symmetrySymbol =
        structure.symmetry?.international || structure.symmetry?.spacegroup_symbol;
      const symmetryKey = symmetrySymbol
        ? `${structure.symmetry?.number ?? "?"} ${symmetrySymbol}`
        : null;
      if (symmetryKey) {
        symmetryCounts.set(symmetryKey, (symmetryCounts.get(symmetryKey) || 0) + 1);
      }

      if (structure.render?.png) renderedCount += 1;
      if (structure.cif) cifCount += 1;
      if (structure.soap_summary?.file_path) soapCount += 1;
      if (structure.features?.magpie) magpieCount += 1;

      const minDistance = Number(structure.geometry?.min_distance);
      if (Number.isFinite(minDistance)) {
        globalMinDistance =
          globalMinDistance === null
            ? minDistance
            : Math.min(globalMinDistance, minDistance);
      }

      const threshold = Number(structure.geometry?.close_contact_threshold);
      if (Number.isFinite(threshold) && closeContactThreshold === null) {
        closeContactThreshold = threshold;
      }

      const closeContacts = Number(structure.geometry?.num_close_contacts ?? 0);
      if (closeContacts > 0) {
        closeContactStructureCount += 1;
        issueFlags.push({
          code: `CLOSE_CONTACTS_${index}`,
          severity: "warn",
          evidence: `Structure ${index} (${formula}) has ${closeContacts} close contact${
            closeContacts === 1 ? "" : "s"
          }${Number.isFinite(threshold) ? ` below ${formatMetricValue(threshold, 2)} A` : ""}.`,
        });
      }

      const structureWarnings = Array.isArray(structure.warnings)
        ? structure.warnings.filter(Boolean)
        : [];
      if (structureWarnings.length > 0) {
        structureWarningCount += structureWarnings.length;
        issueFlags.push({
          code: `STRUCTURE_${index}_WARNING`,
          severity: "warn",
          evidence: `Structure ${index} (${formula}): ${structureWarnings.join(
            " | "
          )}`,
        });
      }
    });

    const topSymmetry = [...symmetryCounts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 6)
      .map(([label, count]) => ({ label, count }));
    const numGroups =
      metricsData.dedup_summary?.num_groups ??
      (groupCounts.size > 0 ? groupCounts.size : null);
    const largestGroupSize =
      groupCounts.size > 0 ? Math.max(...groupCounts.values()) : null;
    const toolVersions = metricsData.tool_versions || {};
    const toolVersionText = ["ase", "pymatgen", "spglib"]
      .map((name) => `${name} ${toolVersions[name] || "?"}`)
      .join(" | ");

    const summaryParts = [];
    if (structures.length > 0) {
      summaryParts.push(
        `${structures.length} structure${structures.length === 1 ? "" : "s"} parsed from extxyz`
      );
    }
    if (numGroups) {
      summaryParts.push(
        `${numGroups} unique dedup group${numGroups === 1 ? "" : "s"}`
      );
    }
    if (globalMinDistance !== null) {
      summaryParts.push(
        `global minimum distance ${formatMetricValue(globalMinDistance, 2)} A`
      );
    }
    if (structures.length > 0) {
      if (closeContactStructureCount === 0) {
        summaryParts.push(
          `no close contacts${
            closeContactThreshold !== null
              ? ` below ${formatMetricValue(closeContactThreshold, 2)} A`
              : ""
          }`
        );
      } else {
        summaryParts.push(
          `${closeContactStructureCount} structure${
            closeContactStructureCount === 1 ? "" : "s"
          } flagged for close contacts`
        );
      }
    }
    if (soapCount > 0 || magpieCount > 0) {
      summaryParts.push(
        `feature coverage: SOAP ${soapCount}/${structures.length || 0}, Magpie ${
          magpieCount
        }/${structures.length || 0}`
      );
    }

    return {
      structuresCount: structures.length,
      renderedCount,
      cifCount,
      soapCount,
      magpieCount,
      globalMinDistance,
      closeContactThreshold,
      closeContactStructureCount,
      structureWarningCount,
      jobWarningCount: jobWarnings.length,
      numGroups,
      largestGroupSize,
      topSymmetry,
      uniqueSymmetryCount: symmetryCounts.size,
      issueFlags,
      level: issueFlags.length > 0 ? "warn" : "success",
      label: issueFlags.length > 0 ? "Warn" : "Pass",
      summary:
        summaryParts.join(" | ") || "MatterGen metrics are available for this run.",
      toolVersionText,
      sourcePath: metricsData.source?.path || metricsData.source?.extxyz || null,
      sourceHash: metricsData.source?.sha256 || null,
      frames:
        metricsData.source?.frames ??
        structures.length ??
        metricsData.core?.ase?.frames ??
        null,
      generatedAt:
        metricsData.timestamps?.generated_at || metricsData.generated_at || null,
      matcherText:
        metricsData.dedup_summary &&
        [
          metricsData.dedup_summary.ltol,
          metricsData.dedup_summary.stol,
          metricsData.dedup_summary.angle_tol,
        ].some((value) => value !== null && value !== undefined)
          ? `ltol ${formatMetricValue(metricsData.dedup_summary.ltol, 2)} | stol ${formatMetricValue(
              metricsData.dedup_summary.stol,
              2
            )} | angle ${formatMetricValue(
              metricsData.dedup_summary.angle_tol,
              1
            )}`
          : "-",
    };
  }, [metricsData]);

  const mattergenStructureRows = useMemo(() => {
    if (!metricsData) return [];

    const structures = Array.isArray(metricsData.structures)
      ? metricsData.structures
      : [];

    return structures.map((structure, index) => {
      const natoms = Number(structure.natoms);
      const volume = Number(structure.lattice?.volume);
      const volumePerAtom =
        Number.isFinite(natoms) && natoms > 0 && Number.isFinite(volume)
          ? volume / natoms
          : null;
      const closeContacts = Number(structure.geometry?.num_close_contacts ?? 0);
      const rowWarnings = Array.isArray(structure.warnings)
        ? structure.warnings.filter(Boolean)
        : [];
      const symmetrySymbol =
        structure.symmetry?.international || structure.symmetry?.spacegroup_symbol;

      return {
        index,
        formula: structure.reduced_formula || `Structure ${index}`,
        natoms: Number.isFinite(natoms) ? natoms : "-",
        symmetry: symmetrySymbol
          ? `${structure.symmetry?.number ?? "?"} ${symmetrySymbol}`
          : "-",
        volumePerAtom,
        minDistance: structure.geometry?.min_distance,
        minDistancePair: structure.geometry?.min_distance_pair?.pair || null,
        closeContacts,
        dedup:
          structure.dedup?.group_id !== null &&
          structure.dedup?.group_id !== undefined
            ? `G${structure.dedup.group_id}${
                structure.dedup?.group_size
                  ? ` x${structure.dedup.group_size}`
                  : ""
              }`
            : "-",
        soap:
          structure.soap_summary?.n_features !== null &&
          structure.soap_summary?.n_features !== undefined
            ? structure.soap_summary.n_features
            : "-",
        magpie: structure.features?.magpie ? "Yes" : "No",
        warnings: rowWarnings.length + (closeContacts > 0 ? 1 : 0),
      };
    });
  }, [metricsData]);

  const visibleMattergenStructures = showAllMattergenStructures
    ? mattergenStructureRows
    : mattergenStructureRows.slice(0, MATTERGEN_STRUCTURE_PREVIEW_LIMIT);
  const mattergenHasExpandableRows =
    mattergenStructureRows.length > MATTERGEN_STRUCTURE_PREVIEW_LIMIT;
  const mattergenVisibleFlags = mattergenOverview
    ? mattergenOverview.issueFlags.slice(0, 8)
    : [];
  const mattergenHasMoreFlags =
    (mattergenOverview?.issueFlags.length || 0) > mattergenVisibleFlags.length;

  const vaspMetricsRootDir =
    vaspMetricsData?.meta?.root_dir || vaspMetricsData?.meta?.workdir || "";

  const vtstPlotItems = useMemo(() => {
    if (!vaspMetricsData || !activeVaspJobId) return [];
    const plotDefs = [
      {
        key: "barrier_raw",
        label: "Discrete barrier",
        relPath: relativeArtifactPath(
          vaspMetricsData.artifacts?.barrier_raw_png,
          vaspMetricsRootDir
        ),
      },
      {
        key: "barrier_spline",
        label: "Spline barrier",
        relPath: relativeArtifactPath(
          vaspMetricsData.artifacts?.barrier_spline_png,
          vaspMetricsRootDir
        ),
      },
      {
        key: "force_path",
        label: "Force along path",
        relPath: relativeArtifactPath(
          vaspMetricsData.artifacts?.force_along_path_png,
          vaspMetricsRootDir
        ),
      },
      {
        key: "reaction_movie",
        label: "Reaction movie",
        relPath: relativeArtifactPath(
          vaspMetricsData.artifacts?.reaction_gif,
          vaspMetricsRootDir
        ),
      },
      {
        key: "endpoint_vs_ts",
        label: "Endpoint vs highest-energy image",
        relPath: relativeArtifactPath(
          vaspMetricsData.artifacts?.endpoint_vs_ts_png,
          vaspMetricsRootDir
        ),
      },
    ];

    return plotDefs
      .filter((item) => item.relPath)
      .map((item) => ({
        ...item,
        src: `${API_BASE}/api/vasp/jobs/${activeVaspJobId}/artifacts/${encodeURIComponent(
          item.relPath
        )}`,
      }));
  }, [vaspMetricsData, activeVaspJobId, vaspMetricsRootDir]);

  const hdf5PlotItems = useMemo(() => {
    if (!vaspMetricsData || !activeVaspJobId) return [];
    const plotLabels = {
      energy: "Energy trace",
      dos: "Density of states",
      band: "Band structure",
      phonon_dos: "Phonon DOS",
      phonon_band: "Phonon band",
      magnetism: "Magnetism",
    };
    return Object.entries(vaspMetricsData.artifacts?.plots || {})
      .map(([key, value]) => {
        const relPath = relativeArtifactPath(value, vaspMetricsRootDir);
        if (!relPath) return null;
        return {
          key,
          label: plotLabels[key] || key,
          relPath,
          src: `${API_BASE}/api/vasp/jobs/${activeVaspJobId}/artifacts/${encodeURIComponent(
            relPath
          )}`,
        };
      })
      .filter(Boolean);
  }, [vaspMetricsData, activeVaspJobId, vaspMetricsRootDir]);

  const vtstArtifactItems = useMemo(() => {
    if (!vaspMetricsData || !activeVaspJobId) return [];
    const candidates = [
      {
        key: "vtst_metrics",
        label: "vtst_metrics.json",
        relPath: "vtst_metrics.json",
      },
      {
        key: "image_table",
        label: "image_energy_table.csv",
        relPath: relativeArtifactPath(
          vaspMetricsData.artifacts?.image_energy_table_csv,
          vaspMetricsRootDir
        ) || "image_energy_table.csv",
      },
      {
        key: "neb_dat",
        label: "neb.dat",
        relPath: relativeArtifactPath(vaspMetricsData.artifacts?.neb_dat, vaspMetricsRootDir),
      },
      {
        key: "spline_dat",
        label: "spline.dat",
        relPath: relativeArtifactPath(
          vaspMetricsData.artifacts?.spline_dat,
          vaspMetricsRootDir
        ),
      },
      {
        key: "exts_dat",
        label: "exts.dat",
        relPath: relativeArtifactPath(vaspMetricsData.artifacts?.exts_dat, vaspMetricsRootDir),
      },
      {
        key: "reaction_movie",
        label: "reaction_movie.gif",
        relPath: relativeArtifactPath(
          vaspMetricsData.artifacts?.reaction_gif,
          vaspMetricsRootDir
        ),
      },
      {
        key: "endpoint_vs_ts",
        label: "endpoint_vs_ts.png",
        relPath: relativeArtifactPath(
          vaspMetricsData.artifacts?.endpoint_vs_ts_png,
          vaspMetricsRootDir
        ),
      },
    ];

    const allowed = new Set(activeVaspJob?.meta?.available_output_files || []);
    return candidates
      .filter((item) => item.relPath && (allowed.size === 0 || allowed.has(item.relPath)))
      .map((item) => ({
        ...item,
        href: `${API_BASE}/api/vasp/jobs/${activeVaspJobId}/artifacts/${encodeURIComponent(
          item.relPath
        )}`,
      }));
  }, [vaspMetricsData, activeVaspJobId, activeVaspJob, vaspMetricsRootDir]);

  const hdf5ArtifactItems = useMemo(() => {
    if (!vaspMetricsData || !activeVaspJobId) return [];
    const metricsRelPath =
      relativeArtifactPath(activeVaspJob?.meta?.metrics_path, vaspMetricsRootDir) ||
      "HDF5_metrics.json";
    const plotPaths = Object.values(vaspMetricsData.artifacts?.plots || {}).map((value) =>
      relativeArtifactPath(value, vaspMetricsRootDir)
    );
    const candidates = [
      {
        key: "hdf5_metrics",
        label: metricsRelPath.split("/").pop(),
        relPath: metricsRelPath,
      },
      ...plotPaths.map((relPath) => ({
        key: relPath,
        label: relPath.split("/").pop(),
        relPath,
      })),
    ];
    const allowed = new Set(activeVaspJob?.meta?.available_output_files || []);
    return candidates
      .filter(
        (item) =>
          item.relPath && (allowed.size === 0 || allowed.has(item.relPath))
      )
      .map((item) => ({
        ...item,
        href: `${API_BASE}/api/vasp/jobs/${activeVaspJobId}/artifacts/${encodeURIComponent(
          item.relPath
        )}`,
      }));
  }, [vaspMetricsData, activeVaspJobId, activeVaspJob, vaspMetricsRootDir]);

  const vtstImageTable = vaspMetricsData?.image_table || [];
  const vtstQcFlags = vaspMetricsData?.qc?.flags || [];
  const vtstKeyAtomMoves =
    vaspMetricsData?.structure_change_summary?.key_atom_displacements || [];
  const wannierVisualization = vaspMetricsData?.visualization || {};
  const wannierWarnings = vaspMetricsData?.warnings || [];
  const wannierDetailsRelPath = relativeArtifactPath(
    vaspMetricsData?.details_files?.wannier_details_json,
    vaspMetricsRootDir
  );
  const wannierFunctionPreview =
    vaspMetricsData?.wannier_functions_preview || vaspMetricsData?.wannier_functions || [];
  const wannierFunctions =
    wannierDetailsData?.wannier_functions || vaspMetricsData?.wannier_functions || [];
  const wannierFunctionCount =
    vaspMetricsData?.spread_summary?.count ||
    vaspMetricsData?.num_wann ||
    wannierFunctions.length ||
    wannierFunctionPreview.length;
  const wannierSpreadSummary = vaspMetricsData?.spread_summary || {};
  const wannierQuality = vaspMetricsData?.quality_assessment || {};
  const wannierTightBinding = vaspMetricsData?.tight_binding || {};
  const wannierTbCompactness =
    wannierTightBinding?.compactness_assessment || {};
  const allowedVaspOutputs = new Set(
    activeVaspJob?.meta?.available_output_files || []
  );
  const wannierArtifacts = Object.entries(
    vaspMetricsData?.artifacts?.files || {}
  )
    .map(([key, value]) => {
      const relPath = relativeArtifactPath(value, vaspMetricsRootDir) || key;
      return relPath &&
        (allowedVaspOutputs.size === 0 || allowedVaspOutputs.has(relPath))
        ? {
            key,
            label: relPath,
            href: buildVaspArtifactHref(API_BASE, activeVaspJobId, relPath),
          }
        : null;
    })
    .filter(Boolean);
  const wannierPlotItems = [
    wannierVisualization.structure_centers_png && {
      key: "structure-centers",
      label: "Structure + Wannier centers",
      relPath:
        relativeArtifactPath(
          wannierVisualization.structure_centers_png,
          vaspMetricsRootDir
        ) || "plots/wannier_centers_overlay.png",
    },
    wannierVisualization.wf_overview_png && {
      key: "wf-overview",
      label: "WF overview",
      relPath:
        relativeArtifactPath(
          wannierVisualization.wf_overview_png,
          vaspMetricsRootDir
        ) || "plots/wf_overview.png",
    },
    ...(wannierVisualization.orbital_pngs || []).map((item) => ({
      key: `wf-plot-${item.index}`,
      label: `WF ${String(item.index).padStart(3, "0")}`,
      relPath:
        relativeArtifactPath(item.path, vaspMetricsRootDir) ||
        `plots/wf_${String(item.index).padStart(3, "0")}.png`,
    })),
  ]
    .filter(Boolean)
    .filter(
      (item) =>
        item.relPath &&
        (allowedVaspOutputs.size === 0 || allowedVaspOutputs.has(item.relPath))
    )
    .map((item) => ({
      ...item,
      src: buildVaspArtifactHref(API_BASE, activeVaspJobId, item.relPath),
    }));
  const wannierTbPlotItems = [
    wannierTightBinding?.artifacts?.hopping_vs_distance_png && {
      key: "tb-distance",
      label: "Hopping vs distance",
      relPath: relativeArtifactPath(
        wannierTightBinding.artifacts.hopping_vs_distance_png,
        vaspMetricsRootDir
      ),
    },
    wannierTightBinding?.artifacts?.hopping_pair_heatmap_png && {
      key: "tb-heatmap",
      label: "Orbital-pair heatmap",
      relPath: relativeArtifactPath(
        wannierTightBinding.artifacts.hopping_pair_heatmap_png,
        vaspMetricsRootDir
      ),
    },
    wannierTightBinding?.artifacts?.hopping_graph_png && {
      key: "tb-graph",
      label: "Truncated hopping graph",
      relPath: relativeArtifactPath(
        wannierTightBinding.artifacts.hopping_graph_png,
        vaspMetricsRootDir
      ),
    },
    wannierTightBinding?.artifacts?.hopping_truncation_png && {
      key: "tb-truncation",
      label: "Cutoff trend",
      relPath: relativeArtifactPath(
        wannierTightBinding.artifacts.hopping_truncation_png,
        vaspMetricsRootDir
      ),
    },
  ]
    .filter(Boolean)
    .filter(
      (item) =>
        item.relPath &&
        (allowedVaspOutputs.size === 0 || allowedVaspOutputs.has(item.relPath))
    )
    .map((item) => ({
      ...item,
      src: buildVaspArtifactHref(API_BASE, activeVaspJobId, item.relPath),
    }));
  const wannierTbArtifactItems = [
    {
      key: "hr",
      label: "wannier90_hr.dat",
      relPath: relativeArtifactPath(
        wannierTightBinding?.artifacts?.hr_dat,
        vaspMetricsRootDir
      ),
    },
    {
      key: "r",
      label: "wannier90_r.dat",
      relPath: relativeArtifactPath(
        wannierTightBinding?.artifacts?.r_dat,
        vaspMetricsRootDir
      ),
    },
    {
      key: "tb",
      label: "wannier90_tb.dat",
      relPath: relativeArtifactPath(
        wannierTightBinding?.artifacts?.tb_dat,
        vaspMetricsRootDir
      ),
    },
    {
      key: "hamiltonian",
      label: "hamiltonian.json",
      relPath: relativeArtifactPath(
        wannierTightBinding?.artifacts?.hamiltonian_json,
        vaspMetricsRootDir
      ),
    },
    {
      key: "graph",
      label: "hopping_graph.json",
      relPath: relativeArtifactPath(
        wannierTightBinding?.artifacts?.hopping_graph_json,
        vaspMetricsRootDir
      ),
    },
  ]
    .filter(
      (item) =>
        item.relPath &&
        (allowedVaspOutputs.size === 0 || allowedVaspOutputs.has(item.relPath))
    )
    .map((item) => ({
      ...item,
      href: buildVaspArtifactHref(API_BASE, activeVaspJobId, item.relPath),
    }));
  const wannierTopTerms = (wannierTightBinding?.top_terms || []).slice(0, 8);
  const wannierTopPairs = (wannierTightBinding?.top_orbital_pairs || []).slice(
    0,
    8
  );
  const wannierTruncationSummary =
    wannierTightBinding?.truncation_summary || [];
  const postw90Summary = vaspMetricsData?.summaries || {};
  const postw90Warnings = vaspMetricsData?.warnings || [];
  const postw90GeneratedFiles = vaspMetricsData?.generated_files || [];
  const postw90PlotItems = Object.entries(vaspMetricsData?.artifacts?.plots || {})
    .map(([key, value]) => {
      const relPath = relativeArtifactPath(value, vaspMetricsRootDir);
      return relPath &&
        (allowedVaspOutputs.size === 0 || allowedVaspOutputs.has(relPath))
        ? {
            key,
            label: key.replaceAll("_", " "),
            src: buildVaspArtifactHref(API_BASE, activeVaspJobId, relPath),
          }
        : null;
    })
    .filter(Boolean);
  const postw90ArtifactItems = Object.entries(vaspMetricsData?.artifacts?.files || {})
    .map(([key, value]) => {
      const relPath = relativeArtifactPath(value, vaspMetricsRootDir) || key;
      return relPath &&
        (allowedVaspOutputs.size === 0 || allowedVaspOutputs.has(relPath))
        ? {
            key,
            label: relPath,
            href: buildVaspArtifactHref(API_BASE, activeVaspJobId, relPath),
          }
        : null;
    })
    .filter(Boolean);
  const postw90BandSummary = postw90Summary.band_interp || {};
  const postw90DosSummary = postw90Summary.dos || {};
  const postw90AhcSummary = postw90Summary.berry_ahc || {};
  const postw90FermiSummary = postw90Summary.fermi_surface || {};
  const postw90BoltzSummary = postw90Summary.boltzwann || {};
  const visibleWannierFunctions = showAllWannierFunctions
    ? wannierFunctions.length > 0
      ? wannierFunctions
      : wannierFunctionPreview
    : wannierFunctionPreview.slice(0, WANNIER_FUNCTION_PREVIEW_LIMIT);
  const visibleWannierPlots = showAllWannierPlots
    ? wannierPlotItems
    : wannierPlotItems.slice(0, WANNIER_PLOT_PREVIEW_LIMIT);
  const hdf5QcFlags = vaspMetricsData?.qc?.flags || [];
  const hdf5QcOverview = summarizeHdf5Qc(vaspMetricsData);
  const hdf5PluginSummary = vaspMetricsData?.postprocess || {};
  const hdf5Spacegroup = vaspMetricsData?.crystallography_summary?.spacegroup || {};
  const hdf5HighPath =
    vaspMetricsData?.crystallography_summary?.high_symmetry_path || {};
  const hdf5BandDos = hdf5PluginSummary?.plugin_results?.band_dos || {};

  const visibleJobs = showAllJobs ? jobs : jobs.slice(0, JOBS_PREVIEW_LIMIT);
  const visibleVaspJobs = showAllVaspJobs
    ? vaspJobs
    : vaspJobs.slice(0, VASP_JOBS_PREVIEW_LIMIT);

  return (
    <div className="page" data-mode={activeMode}>
      <header className="header">
        <div className="brand-shell">
          <div className="brand-copy">
            <p className="eyebrow">{headerCopy.eyebrow}</p>
            <h1>MatterMind</h1>
            <div className="brand-workflow-row">
              <span className="brand-workflow-title">{headerCopy.workflowTitle}</span>
              <span className="brand-workflow-divider" aria-hidden="true" />
              <span className="brand-workflow-note">{headerCopy.workflowNote}</span>
            </div>
            <p className="subhead">{headerCopy.subhead}</p>
          </div>
        </div>
        <div className="header__meta">
          <div className="mode-toggle">
            <button
              type="button"
              className={activeMode === "mattergen" ? "mode-btn is-active" : "mode-btn"}
              onClick={() => setActiveMode("mattergen")}
            >
              MatterGen
            </button>
            <button
              type="button"
              className={activeMode === "vasp" ? "mode-btn is-active" : "mode-btn"}
              onClick={() => setActiveMode("vasp")}
            >
              VASP
            </button>
          </div>
          <div className="chip">API {API_BASE || "same-origin"}</div>
          <button
            className="ghost"
            type="button"
            onClick={activeMode === "vasp" ? loadVaspJobs : loadJobs}
          >
            {activeMode === "vasp"
              ? vaspRefreshing
                ? "Refreshing..."
                : "Refresh"
              : refreshing
              ? "Refreshing..."
              : "Refresh"}
          </button>
        </div>
      </header>

      {(activeMode === "vasp" ? vaspError : lastError) && (
        <div className="alert">
          <span>!</span>
          <div>{activeMode === "vasp" ? vaspError : lastError}</div>
        </div>
      )}

      <main className="grid">
        {activeMode === "mattergen" ? (
          <>
        <section className="card form-card">
          <div className="card__header">
            <h2>Launch run</h2>
            <span className="pill">queue</span>
          </div>
          <form onSubmit={submitJob} className="form">
            <label className="field">
              <span>Model</span>
              <select
                value={modelName}
                onChange={(event) => setModelName(event.target.value)}
              >
                {Object.entries(modelGroups).map(([group, models]) => (
                  <optgroup key={group} label={group}>
                    {models.map((model) => (
                      <option key={model.label} value={model.label}>
                        {model.label}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              <small>{config.description}</small>
            </label>

            <div className="field-row">
              <label className="field">
                <span>Batch size</span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={batchSize}
                  onChange={(event) => setBatchSize(event.target.value)}
                />
              </label>
              <label className="field">
                <span>Num batches</span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={numBatches}
                  onChange={(event) => setNumBatches(event.target.value)}
                />
              </label>
            </div>

            {config.fields.length > 0 && (
              <div className="section">
                <h3>Conditioning</h3>
                {config.fields.map((field) => (
                  <label className="field" key={field.key}>
                    <span>{field.label}</span>
                    <input
                      type={field.type}
                      step={field.step}
                      placeholder={field.placeholder}
                      value={properties[field.key] ?? ""}
                      onChange={(event) =>
                        setProperties((prev) => ({
                          ...prev,
                          [field.key]: event.target.value,
                        }))
                      }
                    />
                  </label>
                ))}
              </div>
            )}

            {config.guidance && (
              <label className="field">
                <span>Diffusion guidance factor</span>
                <input
                  type="number"
                  step="0.1"
                  placeholder="2.0"
                  value={guidance}
                  onChange={(event) => setGuidance(event.target.value)}
                />
              </label>
            )}

            <button className="primary" type="submit" disabled={submitting}>
              {submitting ? "Launching..." : "Launch run"}
            </button>
          </form>

          <div className="payload">
            <div className="payload__header">Payload preview</div>
            <pre>{JSON.stringify(payloadPreview, null, 2)}</pre>
          </div>
        </section>

        <section className="card jobs-card">
          <div className="card__header">
            <h2>Runs</h2>
            <div className="runs-actions">
              {jobs.length > JOBS_PREVIEW_LIMIT && (
                <button
                  type="button"
                  className="ghost ghost--small"
                  onClick={() => setShowAllJobs((prev) => !prev)}
                >
                  {showAllJobs ? "Show recent" : "Show all"}
                </button>
              )}
              <span className="pill">{jobs.length}</span>
            </div>
          </div>
          {jobs.length === 0 ? (
            <p className="empty">No jobs yet. Launch your first run.</p>
          ) : (
            <ul className="job-list">
              {visibleJobs.map((job) => (
                <li key={job.job_id}>
                  <button
                    type="button"
                    className={
                      job.job_id === activeJobId
                        ? "job-item is-active"
                        : "job-item"
                    }
                    onClick={() => setActiveJobId(job.job_id)}
                  >
                    <div>
                      <div className="job-title">
                        {job.meta?.model_name || "unknown model"}
                      </div>
                      <div className="job-sub">
                        {job.job_id.slice(0, 8)}
                        {" "} - {" "}
                        {formatDateTime(job.created_at)}
                      </div>
                    </div>
                    <span
                      className={`status ${
                        STATUS_TONE[job.status] || "status--muted"
                      }`}
                    >
                      {job.status}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card detail-card full-span">
          <div className="card__header">
            <h2>Active run</h2>
            <span className="pill">{activeJob?.status || "-"}</span>
          </div>
          {!activeJob ? (
            <p className="empty">Select a job to see details.</p>
          ) : (
            <div className="detail-grid">
              <div>
                <h3>Overview</h3>
                <div className="kv">
                  <div>Job ID</div>
                  <div className="mono">{activeJob.job_id}</div>
                  <div>Model</div>
                  <div>{activeJob.meta?.model_name}</div>
                  <div>Batch size</div>
                  <div>{activeJob.meta?.batch_size}</div>
                  <div>Num batches</div>
                  <div>{activeJob.meta?.num_batches}</div>
                  <div>Created</div>
                  <div>{formatDateTime(activeJob.created_at)}</div>
                </div>
              </div>
              <div>
                <h3>Artifacts</h3>
                {!canDownloadArtifacts ? (
                  <div className="empty">Available after run completes.</div>
                ) : (
                  <>
                    <div className="artifact-subtitle">Native outputs</div>
                    <div className="artifact-list artifact-list--compact artifact-list--dense">
                      {ARTIFACTS.map((artifact) => (
                        <a
                          key={artifact}
                          className="artifact artifact--compact"
                          href={`${API_BASE}/api/jobs/${
                            activeJob.job_id
                          }/artifacts/${encodeURIComponent(artifact)}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <span className="artifact-copy">
                            <span className="artifact-file">{artifact}</span>
                            <span className="artifact-meta">native output</span>
                          </span>
                          <span className="arrow">Download</span>
                        </a>
                      ))}
                    </div>
                    <div className="artifact-subtitle">
                      Derived outputs (post-processed)
                    </div>
                    {metricsError && (
                      <div className="analysis-error">{metricsError}</div>
                    )}
                    {metricsStatus === "missing" ? (
                      <div className="empty">Derived outputs not ready.</div>
                    ) : derivedArtifacts.length === 0 ? (
                      <div className="empty">No derived outputs yet.</div>
                    ) : (
                      <div className="artifact-list artifact-list--compact artifact-list--dense">
                        {derivedArtifacts.map((artifact) => (
                          <a
                            key={artifact.key}
                            className="artifact artifact--compact"
                            href={`${API_BASE}/api/jobs/${
                              activeJob.job_id
                            }/files/${encodeURIComponent(artifact.filename)}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <span className="artifact-copy">
                              <span className="artifact-file">{artifact.label}</span>
                              <span className="artifact-meta">{artifact.filename}</span>
                            </span>
                            <span className="arrow">Download</span>
                          </a>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )}
        </section>

        <section className="card detail-card full-span">
          <div className="card__header">
            <h2>MatterGen metrics</h2>
            <span className="pill">
              {canDownloadArtifacts
                ? mattergenOverview?.structuresCount ?? "-"
                : "-"}
            </span>
          </div>
          {!canDownloadArtifacts ? (
            <div className="empty">Available after run completes.</div>
          ) : metricsStatus === "loading" ? (
            <div className="empty">Loading metrics...</div>
          ) : metricsError ? (
            <div className="analysis-error">{metricsError}</div>
          ) : metricsStatus === "missing" || !metricsData || !mattergenOverview ? (
            <div className="empty">MatterGen metrics are not available yet.</div>
          ) : (
            <>
              <div className="metric-strip">
                <div className="metric-box">
                  <div className="metric-label">Structures</div>
                  <div className="metric-value">
                    {mattergenOverview.structuresCount}
                    <span>frames</span>
                  </div>
                </div>
                <div className="metric-box">
                  <div className="metric-label">Unique groups</div>
                  <div className="metric-value">
                    {mattergenOverview.numGroups ?? "-"}
                    <span>dedup</span>
                  </div>
                </div>
                <div className="metric-box">
                  <div className="metric-label">Global min distance</div>
                  <div className="metric-value">
                    {mattergenOverview.globalMinDistance === null
                      ? "-"
                      : formatMetricValue(
                          mattergenOverview.globalMinDistance,
                          2
                        )}
                    <span>A</span>
                  </div>
                </div>
                <div className="metric-box">
                  <div className="metric-label">SOAP coverage</div>
                  <div className="metric-value">
                    {mattergenOverview.soapCount}/{mattergenOverview.structuresCount}
                    <span>structures</span>
                  </div>
                </div>
                <div className="metric-box">
                  <div className="metric-label">Rendered PNGs</div>
                  <div className="metric-value">
                    {mattergenOverview.renderedCount}/
                    {mattergenOverview.structuresCount}
                    <span>structures</span>
                  </div>
                </div>
              </div>

              <div className="detail-grid">
                <div>
                  <div className="section-heading">
                    <h3>Quality snapshot</h3>
                    <span className={`status status--${mattergenOverview.level}`}>
                      {mattergenOverview.label}
                    </span>
                  </div>
                  <div className="section-summary">{mattergenOverview.summary}</div>
                  <div className="status-cluster">
                    <span className="status status--muted">
                      Job warnings {mattergenOverview.jobWarningCount}
                    </span>
                    <span className="status status--warn">
                      Structure warnings {mattergenOverview.structureWarningCount}
                    </span>
                    <span className="status status--warn">
                      Close-contact hits {mattergenOverview.closeContactStructureCount}
                    </span>
                  </div>
                  <div className="kv">
                    <div>Pipeline status</div>
                    <div>{metricsData.status || "-"}</div>
                    <div>Source extxyz</div>
                    <div>{fileNameFromPath(mattergenOverview.sourcePath) || "-"}</div>
                    <div>SHA256</div>
                    <div className="mono">
                      {mattergenOverview.sourceHash
                        ? `${mattergenOverview.sourceHash.slice(0, 16)}...`
                        : "-"}
                    </div>
                    <div>Generated at</div>
                    <div>{formatDateTime(mattergenOverview.generatedAt)}</div>
                    <div>Frames parsed</div>
                    <div>{mattergenOverview.frames ?? "-"}</div>
                    <div>Tool versions</div>
                    <div>{mattergenOverview.toolVersionText}</div>
                  </div>
                </div>

                <div>
                  <h3>Coverage and symmetry</h3>
                  <div className="kv">
                    <div>CIF exports</div>
                    <div>
                      {mattergenOverview.cifCount}/{mattergenOverview.structuresCount}
                    </div>
                    <div>Magpie features</div>
                    <div>
                      {mattergenOverview.magpieCount}/
                      {mattergenOverview.structuresCount}
                    </div>
                    <div>Symmetry families</div>
                    <div>{mattergenOverview.uniqueSymmetryCount || "-"}</div>
                    <div>Largest dedup group</div>
                    <div>
                      {mattergenOverview.largestGroupSize
                        ? `x${mattergenOverview.largestGroupSize}`
                        : "-"}
                    </div>
                    <div>Matcher tolerances</div>
                    <div>{mattergenOverview.matcherText}</div>
                  </div>
                  <div className="artifact-subtitle">Symmetry mix</div>
                  {mattergenOverview.topSymmetry.length === 0 ? (
                    <div className="empty">No symmetry labels were recorded.</div>
                  ) : (
                    <div className="status-cluster">
                      {mattergenOverview.topSymmetry.map((item) => (
                        <span
                          className="status status--muted"
                          key={`${item.label}-${item.count}`}
                        >
                          {item.label} x{item.count}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="artifact-subtitle">Warnings and flags</div>
              {mattergenVisibleFlags.length === 0 ? (
                <div className="empty">No MatterGen warnings were recorded.</div>
              ) : (
                <>
                  <div className="flag-list">
                    {mattergenVisibleFlags.map((flag, index) => (
                      <div className="flag-item" key={`${flag.code}-${index}`}>
                        <span className="status status--warn">{flag.code}</span>
                        <span>{flag.evidence}</span>
                      </div>
                    ))}
                  </div>
                  {mattergenHasMoreFlags && (
                    <div className="table-toggle">
                      <span className="empty">
                        Showing the first {mattergenVisibleFlags.length} flags. Use
                        the structure table below for per-structure warning counts.
                      </span>
                    </div>
                  )}
                </>
              )}

              <div className="artifact-subtitle">Structure summary</div>
              {mattergenStructureRows.length === 0 ? (
                <div className="empty">No per-structure rows were generated.</div>
              ) : (
                <>
                  <div className="mini-table-wrap">
                    <table className="mini-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>Formula</th>
                          <th>Atoms</th>
                          <th>Symmetry</th>
                          <th>V/atom</th>
                          <th>Min dist</th>
                          <th>Close contacts</th>
                          <th>Dedup</th>
                          <th>SOAP</th>
                          <th>Magpie</th>
                          <th>Warn</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleMattergenStructures.map((row) => (
                          <tr key={`mattergen-structure-${row.index}`}>
                            <td>{row.index}</td>
                            <td>{row.formula}</td>
                            <td>{row.natoms}</td>
                            <td>{row.symmetry}</td>
                            <td>
                              {row.volumePerAtom === null
                                ? "-"
                                : formatMetricValue(row.volumePerAtom, 2)}
                            </td>
                            <td>
                              {row.minDistance === null ||
                              row.minDistance === undefined
                                ? "-"
                                : `${formatMetricValue(row.minDistance, 2)}${
                                    row.minDistancePair
                                      ? ` (${row.minDistancePair})`
                                      : ""
                                  }`}
                            </td>
                            <td>{row.closeContacts}</td>
                            <td>{row.dedup}</td>
                            <td>{row.soap}</td>
                            <td>{row.magpie}</td>
                            <td>{row.warnings}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {mattergenHasExpandableRows && (
                    <div className="table-toggle">
                      <button
                        type="button"
                        className="ghost ghost--small"
                        onClick={() =>
                          setShowAllMattergenStructures((current) => !current)
                        }
                      >
                        {showAllMattergenStructures
                          ? "Show fewer structures"
                          : `Show all ${mattergenStructureRows.length} structures`}
                      </button>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </section>

        <section className="card gallery-card full-span">
          <div className="card__header">
            <h2>Crystal gallery</h2>
            <span className="pill">
              {canDownloadArtifacts ? pngGallery.length : "-"}
            </span>
          </div>
          {!canDownloadArtifacts ? (
            <div className="empty">Available after run completes.</div>
          ) : metricsStatus === "loading" ? (
            <div className="empty">Loading renders...</div>
          ) : metricsError ? (
            <div className="analysis-error">{metricsError}</div>
          ) : pngGallery.length === 0 ? (
            <div className="empty">
              No rendered PNGs yet. Rendered images appear after post-processing.
            </div>
          ) : (
            <>
              <div className="gallery-note">
                Rendered via OVITO during post-processing.
              </div>
              <div className="gallery-grid">
                {pngGallery.map((item) => (
                  <figure className="gallery-item" key={item.key}>
                    <a href={item.src} target="_blank" rel="noreferrer">
                      <img
                        src={item.src}
                        alt={`Structure ${item.index}`}
                        loading="lazy"
                      />
                    </a>
                    <figcaption className="gallery-caption">
                      <span>#{item.index}</span>
                      <span>{item.formula}</span>
                    </figcaption>
                  </figure>
                ))}
              </div>
            </>
          )}
        </section>

        <section className="card log-card full-span">
          <div className="card__header">
            <h2>Live logs</h2>
            <span className={`pill pill--${logStatus}`}>{logStatus}</span>
          </div>
          <div className="log" ref={logBoxRef}>
            {logLines.length === 0 ? (
              <div className="empty">Waiting for log stream...</div>
            ) : (
              <pre>{logLines.join("\n")}</pre>
            )}
          </div>
        </section>

        <section className="card assistant-card full-span">
          <div className="card__header">
            <h2>AI assistant</h2>
            <div className="analysis-actions">
              <div className="analysis-model">
                <span>Model</span>
                <select
                  value={analysisModel}
                  onChange={(event) => setAnalysisModel(event.target.value)}
                  disabled={!canAnalyze || analysisStatus === "loading"}
                >
                  {ANALYSIS_MODELS.map((model) => (
                    <option key={model.value} value={model.value}>
                      {model.label}
                    </option>
                  ))}
                </select>
              </div>
              <span className={`pill pill--analysis-${analysisStatus}`}>
                {analysisStatus}
              </span>
              <button
                className="ghost"
                type="button"
                onClick={runAnalysis}
                disabled={!canAnalyze || analysisStatus === "loading"}
              >
                {analysisStatus === "loading" ? "Analyzing..." : "Analyze"}
              </button>
            </div>
          </div>
          {analysisError && <div className="analysis-error">{analysisError}</div>}
          <div className="assistant-section-title">Analysis</div>
          <div
            className="analysis-body"
            ref={analysisBoxRef}
            onScroll={handleAnalysisScroll}
          >
            {analysisText ? (() => {
              const { reasoning, answer } = splitReasoning(analysisText);
              return (
                <>
                  {reasoning && (
                    <details className="reasoning-block">
                      <summary>Reasoning</summary>
                      <div className="reasoning-content">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {reasoning}
                        </ReactMarkdown>
                      </div>
                    </details>
                  )}
                  {answer ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {answer}
                    </ReactMarkdown>
                  ) : (
                    <div className="empty">Waiting for answer...</div>
                  )}
                </>
              );
            })() : (
              <div className="empty">
                {canAnalyze
                  ? "No analysis yet. Click Analyze to generate."
                  : "Analysis is available after the run finishes."}
              </div>
            )}
          </div>
          <div className="assistant-section-title">Chat</div>
          {chatError && <div className="analysis-error">{chatError}</div>}
          <div className="chat-body" ref={chatBoxRef} onScroll={handleChatScroll}>
            {chatMessages.length === 0 ? (
              <div className="empty">
                {canChat
                  ? "No messages yet. Ask a follow-up question."
                  : "Chat is available after analysis completes."}
              </div>
            ) : (
              chatMessages.map((msg, index) => (
                <div
                  key={msg.id || `${msg.role}-${index}`}
                  className={`chat-message chat-${msg.role}`}
                >
                  <div className="chat-role">
                    {msg.role === "assistant" ? "Assistant" : "You"}
                  </div>
                  <div className="chat-content">
                    {msg.role === "assistant" ? (() => {
                      const { reasoning, answer } = splitReasoning(msg.content);
                      return (
                        <>
                          {reasoning && (
                            <details className="reasoning-block">
                              <summary>Reasoning</summary>
                              <div className="reasoning-content">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                  {reasoning}
                                </ReactMarkdown>
                              </div>
                            </details>
                          )}
                          {answer ? (
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {answer}
                            </ReactMarkdown>
                          ) : (
                            <div className="empty">Waiting for answer...</div>
                          )}
                        </>
                      );
                    })() : (
                      <div>{msg.content}</div>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="chat-input">
            <textarea
              rows="3"
              placeholder={
                canChat
                  ? "Ask a follow-up question about the analysis..."
                  : "Run analysis first to enable chat."
              }
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  if (canChat && chatStatus !== "loading") {
                    sendChat();
                  }
                }
              }}
              disabled={!canChat || chatStatus === "loading"}
            />
            <button
              className="primary"
              type="button"
              onClick={sendChat}
              disabled={!canChat || chatStatus === "loading"}
            >
              {chatStatus === "loading" ? "Sending..." : "Send"}
            </button>
          </div>
        </section>
          </>
        ) : (
          <>
            <section className="card vasp-form-card">
              <div className="card__header">
                <h2>VASP run</h2>
                <span className="pill">vasp</span>
              </div>
              <form onSubmit={submitVaspJob} className="form">
                <label className="field">
                  <span>Job name</span>
                  <input
                    type="text"
                    placeholder="optional label"
                    value={vaspJobName}
                    onChange={(event) => setVaspJobName(event.target.value)}
                  />
                  <small>Optional label for quick identification.</small>
                </label>

                <div className="field-row">
                  <label className="field">
                    <span>Workflow</span>
                    <select
                      value={vaspRunMode}
                      onChange={(event) => setVaspRunMode(event.target.value)}
                    >
                      {VASP_RUN_MODES.map((mode) => (
                        <option key={mode.value} value={mode.value}>
                          {mode.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Executable</span>
                    <select
                      value={vaspExec}
                      onChange={(event) => setVaspExec(event.target.value)}
                    >
                      {VASP_EXECUTABLES.map((exec) => (
                        <option key={exec} value={exec}>
                          {exec}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="field-row">
                  <label className="field">
                    <span>
                      {vaspRunMode === "vtst_neb"
                        ? "NEB MPI processes"
                        : vaspRunMode === "wannier_scf"
                        ? "SCF MPI processes"
                        : vaspRunMode === "wannier_post"
                        ? "Wannier MPI processes"
                        : vaspRunMode === "wannier"
                        ? "Wannier MPI processes"
                        : "MPI processes"}
                    </span>
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={vaspNproc}
                      onChange={(event) => setVaspNproc(event.target.value)}
                    />
                    <small>
                      {vaspRunMode === "vtst_neb"
                        ? "Set this to a multiple of IMAGES from the uploaded INCAR_neb."
                        : vaspRunMode === "wannier_scf"
                        ? "MPI ranks for the initial SCF with the HDF5 VASP build."
                        : vaspRunMode === "wannier_post"
                        ? "MPI ranks for the plain VASP interface step before wannier90.x."
                        : vaspRunMode === "wannier"
                        ? "MPI ranks for the interface VASP step before wannier90.x."
                        : "Total MPI ranks for the standard VASP run."}
                    </small>
                  </label>
                  {vaspRunMode === "vtst_neb" && vaspVtstMode === "relax_first" ? (
                    <label className="field">
                      <span>Endpoint MPI processes</span>
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={vaspEndpointNproc}
                        onChange={(event) =>
                          setVaspEndpointNproc(event.target.value)
                        }
                      />
                      <small>
                        Used only for the preliminary relax runs in endpoint_initial/ and endpoint_final/.
                      </small>
                    </label>
                  ) : vaspRunMode === "vtst_neb" ? (
                    <div className="section">
                      <strong>Endpoint relax</strong>
                      <small>No standalone endpoint relax jobs are launched in this mode.</small>
                    </div>
                  ) : (
                    <div className="section">
                      <strong>{vaspModeConfig.label}</strong>
                      <small>{vaspModeConfig.description}</small>
                      {vaspRunMode === "wannier" && (
                        <small>
                          Upload the post-processing <code>INCAR</code> together with{" "}
                          <code>WAVECAR</code>; backend will run the plain VASP interface step
                          and then execute <code>wannier90.x wannier90</code>.
                        </small>
                      )}
                      {vaspRunMode === "wannier_scf" && (
                        <small>
                          This stage should produce <code>WAVECAR</code> and optionally{" "}
                          <code>CHGCAR</code>, which will be reused by the next Wannier step.
                        </small>
                      )}
                      {vaspRunMode === "wannier_post" && (
                        <small>
                          Backend will copy <code>POSCAR</code>, <code>POTCAR</code>,{" "}
                          <code>KPOINTS</code>, <code>WAVECAR</code>, and optional{" "}
                          <code>CHGCAR</code> from the selected SCF job.
                        </small>
                      )}
                    </div>
                  )}
                </div>

                {vaspRunMode === "vtst_neb" && (
                  <div className="field-row">
                    <label className="field">
                      <span>VTST endpoint mode</span>
                      <select
                        value={vaspVtstMode}
                        onChange={(event) => setVaspVtstMode(event.target.value)}
                      >
                        {VTST_MODE_OPTIONS.map((mode) => (
                          <option key={mode.value} value={mode.value}>
                            {mode.label}
                          </option>
                        ))}
                      </select>
                      <small>
                        {
                          VTST_MODE_OPTIONS.find((mode) => mode.value === vaspVtstMode)
                            ?.description
                        }
                      </small>
                    </label>
                    <div className="section">
                      <strong>{vaspModeConfig.label}</strong>
                      <small>{vaspModeConfig.description}</small>
                      <small>{vaspModeConfig.detail}</small>
                    </div>
                  </div>
                )}

                {vaspRunMode === "wannier_post" && (
                  <div className="section">
                    <label className="field">
                      <span>Source SCF job</span>
                      <select
                        value={vaspSourceJobId}
                        onChange={(event) => setVaspSourceJobId(event.target.value)}
                      >
                        {wannierScfSourceJobs.length === 0 ? (
                          <option value="">No successful Wannier SCF jobs yet</option>
                        ) : (
                          <>
                            <option value="">Select a source SCF job</option>
                            {wannierScfSourceJobs.map((job) => (
                              <option key={job.job_id} value={job.job_id}>
                                {(job.meta?.job_name || "Wannier SCF")} | {job.job_id.slice(0, 8)} |{" "}
                                {formatDateTime(job.created_at)}
                              </option>
                            ))}
                          </>
                        )}
                      </select>
                      <small>
                        Pick a successful SCF run that generated the carry-over files for Wannier.
                      </small>
                    </label>
                    <div className="option-stack">
                      <label className="checkbox-field">
                        <span className="checkbox-field__row">
                          <input
                            type="checkbox"
                            checked={vaspWannierEnableLwriteUnk}
                            onChange={(event) =>
                              setVaspWannierEnableLwriteUnk(event.target.checked)
                            }
                          />
                          <span>Enable <code>LWRITE_UNK = .TRUE.</code></span>
                        </span>
                        <small>
                          Patch <code>INCAR</code> before the interface VASP step.
                        </small>
                      </label>
                      <label className="checkbox-field">
                        <span className="checkbox-field__row">
                          <input
                            type="checkbox"
                            checked={vaspWannierEnablePlot}
                            onChange={(event) =>
                              setVaspWannierEnablePlot(event.target.checked)
                            }
                          />
                          <span>
                            Enable <code>wannier_plot = true</code> and{" "}
                            <code>wannier_plot_format = {DEFAULT_WANNIER_PLOT_FORMAT}</code>
                          </span>
                        </span>
                        <small>
                          Patch generated <code>wannier90.win</code> before{" "}
                          <code>wannier90.x</code>.
                        </small>
                      </label>
                    </div>
                    <small>
                      Wannier volumetric orbital export usually needs both options. For SOC or
                      noncollinear cases, only enable them if you explicitly want to accept the
                      VASP 6.5.0 risk.
                    </small>
                  </div>
                )}

                {vaspRunMode === "vtst_neb" && (
                  <div className="section">
                    <strong>{vaspModeConfig.label}</strong>
                    <small>{vaspModeConfig.description}</small>
                    <small>
                      Backend will read <code>IMAGES</code> from <code>INCAR_neb</code>,
                      prepare <code>POSCAR_initial</code> and <code>POSCAR_final</code>,
                      run <code>nebmake.pl</code>, launch the parent NEB or CI-NEB job,
                      and then parse <code>neb.dat</code>, <code>spline.dat</code>, and{" "}
                      <code>exts.dat</code>.
                    </small>
                  </div>
                )}

                <div
                  className={`dropzone ${vaspDropActive ? "is-active" : ""}`}
                  onDrop={handleVaspDrop}
                  onDragOver={handleVaspDragOver}
                  onDragLeave={handleVaspDragLeave}
                >
                  <input
                    type="file"
                    multiple
                    onChange={(event) => handleVaspFileList(event.target.files)}
                  />
                  <div className="dropzone-text">
                    <strong>{vaspModeConfig.dropTitle}</strong>
                    <span>{vaspModeConfig.dropHint}</span>
                    <span>Click to browse files</span>
                  </div>
                </div>
                {vaspFileError && (
                  <div className="analysis-error">{vaspFileError}</div>
                )}
                <div className="vasp-file-list">
                  <div className="vasp-file-group">
                    <div className="vasp-file-title">Required inputs</div>
                    {vaspRequiredFiles.map((name) => {
                      const hasFile = Boolean(vaspFiles[name]);
                      return (
                        <div
                          key={name}
                          className={`vasp-file-row ${
                            hasFile ? "is-ok" : "is-missing"
                          }`}
                        >
                          <span>{name}</span>
                          <span>{hasFile ? "Ready" : "Missing"}</span>
                          {hasFile && (
                            <button
                              className="ghost ghost--small"
                              type="button"
                              onClick={() => removeVaspFile(name)}
                            >
                              Remove
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <div className="vasp-file-group">
                    <div className="vasp-file-title">Optional inputs</div>
                    {vaspOptionalFiles.map((name) => {
                      const hasFile = Boolean(vaspFiles[name]);
                      return (
                        <div
                          key={name}
                          className={`vasp-file-row ${
                            hasFile ? "is-ok" : "is-optional"
                          }`}
                        >
                          <span>{name}</span>
                          <span>{hasFile ? "Attached" : "Optional"}</span>
                          {hasFile && (
                            <button
                              className="ghost ghost--small"
                              type="button"
                              onClick={() => removeVaspFile(name)}
                            >
                              Remove
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
                {vaspMissingRequired.length > 0 && (
                  <div className="empty">
                    Missing: {vaspMissingRequired.join(", ")}
                  </div>
                )}
                {(needsWannierSource && !hasValidWannierSource) && (
                  <div className="empty">
                    Select a successful Wannier SCF job before starting the post stage.
                  </div>
                )}
                <button className="primary" type="submit" disabled={!vaspCanSubmit || (needsWannierSource && !hasValidWannierSource)}>
                  {vaspSubmitting
                    ? "Submitting..."
                    : vaspRunMode === "wannier_scf"
                    ? "Start SCF run"
                    : vaspRunMode === "wannier_post" || vaspRunMode === "wannier"
                    ? "Start Wannier run"
                    : "Start VASP run"}
                </button>
              </form>
            </section>

            <section className="card vasp-jobs-card">
              <div className="card__header">
                <h2>VASP runs</h2>
                <div className="runs-actions">
                  {vaspJobs.length > VASP_JOBS_PREVIEW_LIMIT && (
                    <button
                      type="button"
                      className="ghost ghost--small"
                      onClick={() => setShowAllVaspJobs((prev) => !prev)}
                    >
                      {showAllVaspJobs ? "Show recent" : "Show all"}
                    </button>
                  )}
                  <span className="pill">{vaspJobs.length}</span>
                </div>
              </div>
              {vaspJobs.length === 0 ? (
                <p className="empty">No VASP jobs yet.</p>
              ) : (
                <ul className="job-list">
                  {visibleVaspJobs.map((job) => (
                    <li key={job.job_id}>
                      <button
                        type="button"
                        className={
                          job.job_id === activeVaspJobId
                            ? "job-item is-active"
                            : "job-item"
                        }
                        onClick={() => setActiveVaspJobId(job.job_id)}
                      >
                        <div>
                          <div className="job-title">
                            {job.meta?.job_name || "VASP run"}
                          </div>
                          <div className="job-sub">
                            {getVaspWorkflowLabel(job.meta?.run_mode)}
                            {" "} - {" "}
                            {job.job_id.slice(0, 8)}
                            {" "} - {" "}
                            {formatDateTime(job.created_at)}
                          </div>
                        </div>
                        <span
                          className={`status ${
                            STATUS_TONE[job.status] || "status--muted"
                          }`}
                        >
                          {job.status}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card vasp-detail-card full-span">
              <div className="card__header">
                <h2>Active VASP run</h2>
                <div className="runs-actions">
                  {(canStopVasp || vaspStopRequested) && (
                    <button
                      type="button"
                      className="ghost ghost--small"
                      onClick={stopVaspJob}
                      disabled={!canStopVasp}
                    >
                      {vaspStopRequested || vaspStopping ? "Stopping..." : "Stop run"}
                    </button>
                  )}
                  <span className="pill">{activeVaspJob?.status || "-"}</span>
                </div>
              </div>
              {!activeVaspJob ? (
                <p className="empty">Select a VASP job to see details.</p>
              ) : (
                <div className="detail-grid">
                  <div>
                    <h3>Overview</h3>
                    <div className="kv">
                      <div>Job ID</div>
                      <div className="mono">{activeVaspJob.job_id}</div>
                      <div>Name</div>
                      <div>{activeVaspJob.meta?.job_name || "-"}</div>
                      <div>Workflow</div>
                      <div>{getVaspWorkflowLabel(activeVaspJob.meta?.run_mode)}</div>
                      <div>VTST mode</div>
                      <div>
                        {activeVaspJob.meta?.run_mode === "vtst_neb"
                          ? VTST_MODE_OPTIONS.find(
                              (mode) => mode.value === activeVaspJob.meta?.vtst_mode
                            )?.label || "-"
                          : "-"}
                      </div>
                      <div>MPI</div>
                      <div>{activeVaspJob.meta?.nproc}</div>
                      <div>Endpoint MPI</div>
                      <div>
                        {activeVaspJob.meta?.run_mode === "vtst_neb" &&
                        activeVaspJob.meta?.vtst_mode === "relax_first"
                          ? activeVaspJob.meta?.endpoint_nproc || "-"
                          : "-"}
                      </div>
                      <div>Source job</div>
                      <div>
                        {["wannier_post", "wannier", "wannier_postw90"].includes(activeVaspJob.meta?.run_mode)
                          ? activeVaspJob.meta?.source_job_id || "-"
                          : "-"}
                      </div>
                      <div>Executable</div>
                      <div>{activeVaspJob.meta?.vasp_exec}</div>
                      {["wannier_post", "wannier"].includes(activeVaspJob.meta?.run_mode) && (
                        <>
                          <div>LWRITE_UNK patch</div>
                          <div>
                            {activeWannierVisualizationOptions.enable_lwrite_unk
                              ? "Enabled"
                              : "Disabled"}
                          </div>
                          <div>wannier_plot patch</div>
                          <div>
                            {activeWannierVisualizationOptions.enable_wannier_plot
                              ? `Enabled (${activeWannierVisualizationOptions.wannier_plot_format || DEFAULT_WANNIER_PLOT_FORMAT})`
                              : "Disabled"}
                          </div>
                        </>
                      )}
                      <div>Created</div>
                      <div>{formatDateTime(activeVaspJob.created_at)}</div>
                      {activeVaspJob.meta?.vtst_images && (
                        <>
                          <div>Images</div>
                          <div>{activeVaspJob.meta.vtst_images}</div>
                        </>
                      )}
                    </div>
                  </div>
                  <div>
                    <h3>Outputs</h3>
                    {!vaspCanDownload ? (
                      <div className="empty">Available after run completes.</div>
                    ) : vaspOutputs.length === 0 ? (
                      <div className="empty">No downloadable outputs were found.</div>
                    ) : (
                      <div className="artifact-list artifact-list--compact">
                        {vaspOutputs.map((artifact) => {
                          const { file, group } = describeArtifact(artifact);
                          return (
                            <a
                              key={artifact}
                              className="artifact artifact--compact"
                              href={`${API_BASE}/api/vasp/jobs/${
                                activeVaspJob.job_id
                              }/artifacts/${encodeURIComponent(artifact)}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <span className="artifact-copy">
                                <span className="artifact-file">{file}</span>
                                {group && (
                                  <span className="artifact-meta">{group}</span>
                                )}
                              </span>
                              <span className="arrow">Download</span>
                            </a>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </section>

            <section className="card vtst-metrics-card full-span">
              <div className="card__header">
                <h2>VASP metrics</h2>
                <span className={`pill pill--analysis-${activeVaspJob ? vaspMetricsStatus : "inactive"}`}>
                  {activeVaspJob ? vaspMetricsStatus : "inactive"}
                </span>
              </div>
              {!activeVaspJob ? (
                <div className="empty">Select a VASP job to inspect metrics.</div>
              ) : activeVaspJob.status !== "SUCCESS" ? (
                <div className="empty">
                  Metrics appear after the VASP job completes successfully.
                </div>
              ) : isActiveWannierScfJob ? (
                <div className="empty">
                  Structured metrics are not implemented for the Wannier SCF stage. Use the
                  Outputs panel to inspect and download SCF carry-over files.
                </div>
              ) : vaspMetricsStatus === "loading" ? (
                <div className="empty">Loading VASP metrics...</div>
              ) : vaspMetricsError ? (
                <div className="analysis-error">{vaspMetricsError}</div>
              ) : !vaspMetricsData ? (
                <div className="empty">VASP metrics are not available yet.</div>
              ) : isActiveVtstJob ? (
                <>
                  <div className="metric-strip">
                    <div className="metric-box">
                      <div className="metric-label">Raw barrier</div>
                      <div className="metric-value">
                        {formatMetricValue(
                          vaspMetricsData.barrier_summary?.barrier_raw_eV
                        )}
                        <span>eV</span>
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Spline barrier</div>
                      <div className="metric-value">
                        {formatMetricValue(
                          vaspMetricsData.barrier_summary?.barrier_spline_eV
                        )}
                        <span>eV</span>
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">TS image</div>
                      <div className="metric-value">
                        {vaspMetricsData.barrier_summary?.ts_image_index ?? "-"}
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Path shape</div>
                      <div className="metric-value metric-value--text">
                        {vaspMetricsData.barrier_summary?.path_monotonic === null ||
                        vaspMetricsData.barrier_summary?.path_monotonic === undefined
                          ? "Unknown"
                          : vaspMetricsData.barrier_summary?.path_monotonic
                          ? "Monotonic"
                          : "Internal peak"}
                      </div>
                    </div>
                  </div>

                  <div className="detail-grid">
                    <div>
                      <h3>Quality checks</h3>
                      <div className="kv">
                        <div>Finished cleanly</div>
                        <div>
                          {vaspMetricsData.qc?.finished_cleanly ? "Yes" : "No"}
                        </div>
                        <div>Endpoint OUTCARs</div>
                        <div>
                          {vaspMetricsData.qc?.endpoint_outcars_present
                            ? "Present"
                            : "Missing"}
                        </div>
                        <div>neb.dat</div>
                        <div>
                          {vaspMetricsData.qc?.neb_dat_present
                            ? "Present"
                            : "Missing"}
                        </div>
                        <div>Image count check</div>
                        <div>
                          {vaspMetricsData.qc?.image_count_matches_input === null
                            ? "-"
                            : vaspMetricsData.qc?.image_count_matches_input
                            ? "Matched"
                            : "Mismatch"}
                        </div>
                        <div>MPI multiple check</div>
                        <div>
                          {vaspMetricsData.qc?.nproc_multiple_of_images === null
                            ? "-"
                            : vaspMetricsData.qc?.nproc_multiple_of_images
                            ? "Passed"
                            : "Failed"}
                        </div>
                      </div>
                      <div className="artifact-subtitle">QC flags</div>
                      {vtstQcFlags.length === 0 ? (
                        <div className="empty">No QC flags.</div>
                      ) : (
                        <div className="flag-list">
                          {vtstQcFlags.map((flag, index) => (
                            <div className="flag-item" key={`${flag.code}-${index}`}>
                              <span className={`status status--${flag.severity === "error" ? "danger" : flag.severity === "warn" ? "warn" : "muted"}`}>
                                {flag.code}
                              </span>
                              <span>{flag.evidence}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <div>
                      <h3>Path summary</h3>
                      <div className="kv">
                        <div>Formula</div>
                        <div>{vaspMetricsData.inputs_summary?.formula || "-"}</div>
                        <div>Images</div>
                        <div>{vaspMetricsData.meta?.n_images ?? "-"}</div>
                        <div>KPOINTS</div>
                        <div>{vaspMetricsData.inputs_summary?.kpoints_summary || "-"}</div>
                        <div>TS coordinate</div>
                        <div>
                          {formatMetricValue(
                            vaspMetricsData.barrier_summary?.ts_path_coordinate
                          )}
                        </div>
                        <div>Total path displacement</div>
                        <div>
                          {formatMetricValue(
                            vaspMetricsData.structure_change_summary
                              ?.total_path_displacement_A
                          )}{" "}
                          A
                        </div>
                      </div>
                      <div className="artifact-subtitle">Key atom displacements</div>
                      {vtstKeyAtomMoves.length === 0 ? (
                        <div className="empty">No displacement summary available.</div>
                      ) : (
                        <div className="mini-table-wrap">
                          <table className="mini-table">
                            <thead>
                              <tr>
                                <th>Atom</th>
                                <th>Element</th>
                                <th>Displacement (A)</th>
                              </tr>
                            </thead>
                            <tbody>
                              {vtstKeyAtomMoves.slice(0, 6).map((item) => (
                                <tr key={`move-${item.index}`}>
                                  <td>{item.index}</td>
                                  <td>{item.element}</td>
                                  <td>{formatMetricValue(item.displacement_A)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="artifact-subtitle">VTST plots</div>
                  {vtstPlotItems.length === 0 ? (
                    <div className="empty">No VTST plots were generated.</div>
                  ) : (
                    <div className="gallery-grid">
                      {vtstPlotItems.map((item) => (
                        <figure className="gallery-item" key={item.key}>
                          <a href={item.src} target="_blank" rel="noreferrer">
                            <img src={item.src} alt={item.label} loading="lazy" />
                          </a>
                          <figcaption className="gallery-caption">
                            <span>{item.label}</span>
                          </figcaption>
                        </figure>
                      ))}
                    </div>
                  )}

                  <div className="artifact-subtitle">Structured outputs</div>
                  {vtstArtifactItems.length === 0 ? (
                    <div className="empty">No VTST structured outputs available.</div>
                  ) : (
                    <div className="artifact-list">
                      {vtstArtifactItems.map((artifact) => (
                        <a
                          key={artifact.key}
                          className="artifact"
                          href={artifact.href}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <span>{artifact.label}</span>
                          <span className="arrow">Download</span>
                        </a>
                      ))}
                    </div>
                  )}

                  <div className="artifact-subtitle">Image table</div>
                  <div className="mini-table-wrap">
                    <table className="mini-table">
                      <thead>
                        <tr>
                          <th>Image</th>
                          <th>Coord</th>
                          <th>Rel E (eV)</th>
                          <th>NEB F (eV/A)</th>
                          <th>Max F (eV/A)</th>
                          <th>Converged</th>
                        </tr>
                      </thead>
                      <tbody>
                        {vtstImageTable.map((row) => (
                          <tr key={`image-${row.image}`}>
                            <td>{row.image}</td>
                            <td>{formatMetricValue(row.path_coordinate, 3)}</td>
                            <td>{formatMetricValue(row.energy_rel_eV)}</td>
                            <td>{formatMetricValue(row.force_eVA ?? row.neb_force_eVA)}</td>
                            <td>{formatMetricValue(row.max_force_eVA)}</td>
                            <td>{row.converged === null ? "-" : row.converged ? "Yes" : "No"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : isActivePostw90Job ? (
                <>
                  <div className="metric-strip">
                    <div className="metric-box">
                      <div className="metric-label">Module</div>
                      <div className="metric-value metric-value--text">
                        {vaspMetricsData.module_label || "-"}
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Source Wannier job</div>
                      <div className="metric-value metric-value--text">
                        {vaspMetricsData.source_step?.job_id
                          ? vaspMetricsData.source_step.job_id.slice(0, 8)
                          : "-"}
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Generated files</div>
                      <div className="metric-value">{postw90GeneratedFiles.length}</div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Warnings</div>
                      <div className="metric-value">{postw90Warnings.length}</div>
                    </div>
                  </div>

                  <div className="detail-grid">
                    <div>
                      <h3>Run summary</h3>
                      <div className="kv">
                        <div>Module key</div>
                        <div>{vaspMetricsData.module || "-"}</div>
                        <div>Seedname</div>
                        <div>{vaspMetricsData.seedname || "-"}</div>
                        <div>Source stage</div>
                        <div>{vaspMetricsData.source_step?.run_mode || "-"}</div>
                        <div>Status</div>
                        <div>{vaspMetricsData.status || "-"}</div>
                        <div>Band points</div>
                        <div>{postw90BandSummary.n_kpoints ?? "-"}</div>
                        <div>DOS points</div>
                        <div>{postw90DosSummary.n_points ?? "-"}</div>
                        <div>AHC points</div>
                        <div>{postw90AhcSummary.n_points ?? "-"}</div>
                        <div>Fermi surface</div>
                        <div>{postw90FermiSummary.format || "-"}</div>
                      </div>

                      {Object.keys(vaspMetricsData.module_params || {}).length > 0 && (
                        <>
                          <div className="artifact-subtitle">Injected parameters</div>
                          <div className="mini-table-wrap">
                            <table className="mini-table">
                              <thead>
                                <tr>
                                  <th>Key</th>
                                  <th>Value</th>
                                </tr>
                              </thead>
                              <tbody>
                                {Object.entries(vaspMetricsData.module_params || {}).map(
                                  ([key, value]) => (
                                    <tr key={`postw90-param-${key}`}>
                                      <td>{key}</td>
                                      <td>{String(value)}</td>
                                    </tr>
                                  )
                                )}
                              </tbody>
                            </table>
                          </div>
                        </>
                      )}
                    </div>
                    <div>
                      <h3>Generated outputs</h3>
                      {postw90ArtifactItems.length === 0 ? (
                        <div className="empty">No postw90 outputs were recorded.</div>
                      ) : (
                        <div className="artifact-list artifact-list--compact artifact-list--dense">
                          {postw90ArtifactItems.map((artifact) => (
                            <a
                              key={artifact.key}
                              className="artifact artifact--compact"
                              href={artifact.href}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <span className="artifact-copy">
                                <span className="artifact-file">{artifact.label}</span>
                              </span>
                              <span className="arrow">Open</span>
                            </a>
                          ))}
                        </div>
                      )}

                      <div className="artifact-subtitle">Warnings</div>
                      {postw90Warnings.length === 0 ? (
                        <div className="empty">No warning lines were captured from postw90.out.</div>
                      ) : (
                        <div className="flag-list">
                          {postw90Warnings.map((warning, index) => (
                            <div className="flag-item" key={`postw90-warning-${index}`}>
                              <span className="status status--warn">Warn</span>
                              <span>{warning}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="artifact-subtitle">postw90 plots</div>
                  {postw90PlotItems.length === 0 ? (
                    <div className="empty">No postw90 plots were generated for this module.</div>
                  ) : (
                    <div className="thumb-grid thumb-grid--compact">
                      {postw90PlotItems.map((item) => (
                        <figure className="thumb-card" key={item.key}>
                          <a href={item.src} target="_blank" rel="noreferrer">
                            <img src={item.src} alt={item.label} loading="lazy" />
                          </a>
                          <figcaption className="thumb-caption">
                            <span>{item.label}</span>
                          </figcaption>
                        </figure>
                      ))}
                    </div>
                  )}

                  {postw90GeneratedFiles.length > 0 && (
                    <>
                      <div className="artifact-subtitle">New files from postw90</div>
                      <div className="mini-table-wrap">
                        <table className="mini-table">
                          <thead>
                            <tr>
                              <th>File</th>
                            </tr>
                          </thead>
                          <tbody>
                            {postw90GeneratedFiles.map((file) => (
                              <tr key={`postw90-file-${file}`}>
                                <td>{file}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  )}
                </>
              ) : isActiveWannierPostJob ? (
                <>
                  <div className="metric-strip">
                    <div className="metric-box">
                      <div className="metric-label">Quality grade</div>
                      <div className="metric-value metric-value--text">
                        {(wannierQuality.grade || "-").toUpperCase()}
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Converged</div>
                      <div className="metric-value metric-value--text">
                        {formatBooleanMetric(vaspMetricsData.converged)}
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Num Wann</div>
                      <div className="metric-value">
                        {vaspMetricsData.num_wann ?? "-"}
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Omega total</div>
                      <div className="metric-value">
                        {formatMetricValue(vaspMetricsData.omega_total)}
                        <span>Ang^2</span>
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Average spread</div>
                      <div className="metric-value">
                        {formatMetricValue(wannierQuality.average_spread)}
                        <span>Ang^2</span>
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Max spread</div>
                      <div className="metric-value">
                        {formatMetricValue(wannierQuality.max_spread)}
                        <span>Ang^2</span>
                      </div>
                    </div>
                  </div>

                  <div className="detail-grid">
                    <div>
                      <div className="section-heading">
                        <h3>Quality assessment</h3>
                        <span
                          className={`status status--${
                            wannierQuality.grade === "excellent"
                              ? "success"
                              : wannierQuality.grade === "good"
                              ? "warn"
                              : "danger"
                          }`}
                        >
                          {(wannierQuality.grade || "unknown").toUpperCase()}
                        </span>
                      </div>
                      <div className="section-summary">
                        Score {wannierQuality.score ?? "-"} / 100
                      </div>
                      <div className="kv">
                        <div>Seedname</div>
                        <div>{vaspMetricsData.seedname || "-"}</div>
                        <div>Source SCF</div>
                        <div>{vaspMetricsData.source_step?.job_id || "-"}</div>
                        <div>Source stage</div>
                        <div>{vaspMetricsData.source_step?.run_mode || "-"}</div>
                        <div>Checkpoint</div>
                        <div>
                          {vaspMetricsData.artifacts?.files?.["wannier90.chk"]
                            ? "Present"
                            : "Missing"}
                        </div>
                        <div>Total timing</div>
                        <div>
                          {formatMetricValue(vaspMetricsData.timing?.total_seconds, 2)} s
                        </div>
                        <div>Omega I / D / OD</div>
                        <div>
                          {formatMetricValue(vaspMetricsData.omega_I)} /{" "}
                          {formatMetricValue(vaspMetricsData.omega_D)} /{" "}
                          {formatMetricValue(vaspMetricsData.omega_OD)}
                        </div>
                      </div>

                      <div className="artifact-subtitle">Strengths</div>
                      {wannierQuality.reasons?.length ? (
                        <div className="flag-list">
                          {wannierQuality.reasons.map((reason, index) => (
                            <div className="flag-item" key={`wannier-reason-${index}`}>
                              <span className="status status--success">OK</span>
                              <span>{reason}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="empty">No strong positive signals were recorded.</div>
                      )}

                      <div className="artifact-subtitle">Abnormal causes</div>
                      {wannierQuality.abnormal_causes?.length ? (
                        <div className="flag-list">
                          {wannierQuality.abnormal_causes.map((cause, index) => (
                            <div className="flag-item" key={`wannier-cause-${index}`}>
                              <span className="status status--warn">Check</span>
                              <span>{cause}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="empty">No obvious anomalies were detected.</div>
                      )}
                    </div>
                    <div>
                      <h3>Artifacts and warnings</h3>
                      <div className="artifact-subtitle">Parsed files</div>
                      {wannierArtifacts.length === 0 ? (
                        <div className="empty">No parsed Wannier files were recorded.</div>
                      ) : (
                        <div className="artifact-list artifact-list--compact artifact-list--dense">
                          {wannierArtifacts.map((artifact) => (
                            <a
                              key={artifact.key}
                              className="artifact artifact--compact"
                              href={artifact.href}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <span className="artifact-copy">
                                <span className="artifact-file">{artifact.label}</span>
                              </span>
                              <span className="arrow">Open</span>
                            </a>
                          ))}
                        </div>
                      )}
                  <div className="artifact-subtitle">Warnings</div>
                      {wannierWarnings.length === 0 ? (
                        <div className="empty">No warnings captured from wannier90.wout.</div>
                      ) : (
                        <div className="flag-list">
                          {wannierWarnings.map((warning, index) => (
                            <div className="flag-item" key={`wannier-warning-${index}`}>
                              <span className="status status--warn">Warn</span>
                              <span>{warning}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="artifact-subtitle">Visualizations</div>
                  {wannierPlotItems.length === 0 ? (
                    <div className="empty">
                      No Wannier visualization PNGs were generated. Check the warnings above and
                      confirm that UNK/cube outputs were written.
                    </div>
                  ) : (
                    <>
                      <div className="thumb-grid thumb-grid--compact">
                        {visibleWannierPlots.map((item) => (
                          <figure className="thumb-card" key={item.key}>
                            <a href={item.src} target="_blank" rel="noreferrer">
                              <img src={item.src} alt={item.label} loading="lazy" />
                            </a>
                            <figcaption className="thumb-caption">
                              <span>{item.label}</span>
                            </figcaption>
                          </figure>
                        ))}
                      </div>
                      {wannierPlotItems.length > WANNIER_PLOT_PREVIEW_LIMIT && (
                        <div className="table-toggle">
                          <button
                            type="button"
                            className="ghost ghost--small"
                            onClick={() => setShowAllWannierPlots((prev) => !prev)}
                          >
                            {showAllWannierPlots
                              ? "Show fewer visualizations"
                              : `Show all visualizations (${wannierPlotItems.length})`}
                          </button>
                        </div>
                      )}
                    </>
                  )}

                  <div className="artifact-subtitle">Tight-binding model</div>
                  {!wannierTightBinding.available ? (
                    <div className="empty">
                      No computable tight-binding export was detected yet. Confirm that
                      <code> write_hr = true </code>
                      was enabled and the Wannier run finished successfully.
                    </div>
                  ) : (
                    <>
                      <div className="metric-strip">
                        <div className="metric-box">
                          <div className="metric-label">Model dimension</div>
                          <div className="metric-value">
                            {wannierTightBinding.model_dimension ?? "-"}
                          </div>
                        </div>
                        <div className="metric-box">
                          <div className="metric-label">Largest |t|</div>
                          <div className="metric-value">
                            {formatMetricValue(wannierTightBinding.max_hopping_term?.abs)}
                            <span>eV</span>
                          </div>
                        </div>
                        <div className="metric-box">
                          <div className="metric-label">Nearest shell</div>
                          <div className="metric-value">
                            {formatMetricValue(wannierTightBinding.nearest_neighbor?.max_abs)}
                            <span>eV</span>
                          </div>
                        </div>
                        <div className="metric-box">
                          <div className="metric-label">Next shell</div>
                          <div className="metric-value">
                            {formatMetricValue(
                              wannierTightBinding.next_nearest_neighbor?.max_abs
                            )}
                            <span>eV</span>
                          </div>
                        </div>
                        <div className="metric-box">
                          <div className="metric-label">Avg center offset</div>
                          <div className="metric-value">
                            {formatMetricValue(
                              wannierTightBinding.orbital_center_offsets?.average_A
                            )}
                            <span>Ang</span>
                          </div>
                        </div>
                        <div className="metric-box">
                          <div className="metric-label">Compactness</div>
                          <div className="metric-value metric-value--text">
                            {(wannierTbCompactness.verdict || "-").toUpperCase()}
                          </div>
                        </div>
                      </div>

                      <div className="detail-grid">
                        <div>
                          <div className="section-heading">
                            <h3>Model assessment</h3>
                            <span
                              className={`status status--${
                                wannierTbCompactness.verdict === "compact"
                                  ? "success"
                                  : wannierTbCompactness.verdict === "usable"
                                  ? "warn"
                                  : "danger"
                              }`}
                            >
                              {(wannierTbCompactness.verdict || "unknown").toUpperCase()}
                            </span>
                          </div>
                          <div className="section-summary">
                            {wannierTbCompactness.summary ||
                              "Compactness assessment is not available."}
                          </div>
                          <div className="kv">
                            <div>nrpts</div>
                            <div>{wannierTightBinding.nrpts ?? "-"}</div>
                            <div>Total terms</div>
                            <div>{wannierTightBinding.total_terms ?? "-"}</div>
                            <div>Storage mode</div>
                            <div>{wannierTightBinding.storage_mode || "-"}</div>
                            <div>Total |hopping|</div>
                            <div>
                              {formatMetricValue(wannierTightBinding.total_abs_hopping)}
                            </div>
                            <div>Intersite |hopping|</div>
                            <div>
                              {formatMetricValue(wannierTightBinding.intersite_abs_hopping)}
                            </div>
                            <div>Max center offset</div>
                            <div>
                              {formatMetricValue(
                                wannierTightBinding.orbital_center_offsets?.max_A
                              )}{" "}
                              Ang
                            </div>
                          </div>

                          <div className="artifact-subtitle">Assessment notes</div>
                          {wannierTbCompactness.reasons?.length ? (
                            <div className="flag-list">
                              {wannierTbCompactness.reasons.map((reason, index) => (
                                <div className="flag-item" key={`tb-reason-${index}`}>
                                  <span className="status status--success">OK</span>
                                  <span>{reason}</span>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="empty">No positive compactness signals were recorded.</div>
                          )}

                          {(wannierTbCompactness.warnings?.length ||
                            wannierTightBinding.warnings?.length) > 0 && (
                            <>
                              <div className="artifact-subtitle">TB warnings</div>
                              <div className="flag-list">
                                {[
                                  ...(wannierTbCompactness.warnings || []),
                                  ...(wannierTightBinding.warnings || []),
                                ].map((warning, index) => (
                                  <div className="flag-item" key={`tb-warning-${index}`}>
                                    <span className="status status--warn">Warn</span>
                                    <span>{warning}</span>
                                  </div>
                                ))}
                              </div>
                            </>
                          )}
                        </div>

                        <div>
                          <h3>Exports and shells</h3>
                          <div className="artifact-subtitle">Tight-binding exports</div>
                          {wannierTbArtifactItems.length === 0 ? (
                            <div className="empty">No tight-binding export files are available.</div>
                          ) : (
                            <div className="artifact-list artifact-list--compact artifact-list--dense">
                              {wannierTbArtifactItems.map((artifact) => (
                                <a
                                  key={artifact.key}
                                  className="artifact artifact--compact"
                                  href={artifact.href}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  <span className="artifact-copy">
                                    <span className="artifact-file">{artifact.label}</span>
                                  </span>
                                  <span className="arrow">Open</span>
                                </a>
                              ))}
                            </div>
                          )}

                          <div className="artifact-subtitle">Top hopping terms</div>
                          {wannierTopTerms.length === 0 ? (
                            <div className="empty">No hopping terms were parsed from hr.dat.</div>
                          ) : (
                            <div className="mini-table-wrap">
                              <table className="mini-table">
                                <thead>
                                  <tr>
                                    <th>R</th>
                                    <th>i</th>
                                    <th>j</th>
                                    <th>|t| (eV)</th>
                                    <th>Distance (Ang)</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {wannierTopTerms.map((term, index) => (
                                    <tr key={`tb-term-${index}`}>
                                      <td>{(term.translation || []).join(", ") || "-"}</td>
                                      <td>{term.i}</td>
                                      <td>{term.j}</td>
                                      <td>{formatMetricValue(term.abs)}</td>
                                      <td>{formatMetricValue(term.distance_A)}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="artifact-subtitle">Tight-binding plots</div>
                      {wannierTbPlotItems.length === 0 ? (
                        <div className="empty">
                          No tight-binding plots were rendered from hr.dat yet.
                        </div>
                      ) : (
                        <div className="thumb-grid thumb-grid--compact">
                          {wannierTbPlotItems.map((item) => (
                            <figure className="thumb-card" key={item.key}>
                              <a href={item.src} target="_blank" rel="noreferrer">
                                <img src={item.src} alt={item.label} loading="lazy" />
                              </a>
                              <figcaption className="thumb-caption">
                                <span>{item.label}</span>
                              </figcaption>
                            </figure>
                          ))}
                        </div>
                      )}

                      <div className="detail-grid">
                        <div>
                          <div className="artifact-subtitle">Top orbital pairs</div>
                          {wannierTopPairs.length === 0 ? (
                            <div className="empty">No orbital-pair ranking is available.</div>
                          ) : (
                            <div className="mini-table-wrap">
                              <table className="mini-table">
                                <thead>
                                  <tr>
                                    <th>i</th>
                                    <th>j</th>
                                    <th>Max |t| (eV)</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {wannierTopPairs.map((pair, index) => (
                                    <tr key={`tb-pair-${index}`}>
                                      <td>{pair.i}</td>
                                      <td>{pair.j}</td>
                                      <td>{formatMetricValue(pair.max_abs)}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                        <div>
                          <div className="artifact-subtitle">Cutoff trend</div>
                          {wannierTruncationSummary.length === 0 ? (
                            <div className="empty">No truncation summary is available.</div>
                          ) : (
                            <div className="mini-table-wrap">
                              <table className="mini-table">
                                <thead>
                                  <tr>
                                    <th>Cutoff (Ang)</th>
                                    <th>Retained</th>
                                    <th>Error proxy</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {wannierTruncationSummary.map((entry) => (
                                    <tr key={`tb-cutoff-${entry.radius_A}`}>
                                      <td>{formatMetricValue(entry.radius_A, 1)}</td>
                                      <td>{formatMetricValue(entry.retained_fraction, 3)}</td>
                                      <td>{formatMetricValue(entry.error_proxy, 3)}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                      </div>
                    </>
                  )}

                  <div className="artifact-subtitle">postw90 properties</div>
                  <div className="detail-grid">
                    <div className="postw90-launch">
                      <div className="section-heading">
                        <h3>
                          {postw90Module === "fermi_surface"
                            ? "Launch wannier90.x plot"
                            : "Launch postw90.x"}
                        </h3>
                        <span className="status status--success">Next layer</span>
                      </div>
                      <div className="section-summary">
                        Start a derived property job from this Wannier model. The system reuses
                        the current <code>.win</code>/<code>.chk</code>/<code>hr.dat</code>,
                        injects module-specific settings, and submits a new child job.
                      </div>
                      <label className="field">
                        <span>Module</span>
                        <select
                          value={postw90Module}
                          onChange={(event) => setPostw90Module(event.target.value)}
                          disabled={postw90Submitting}
                        >
                          {Object.entries(POSTW90_MODULE_CONFIG).map(([key, config]) => (
                            <option key={key} value={key}>
                              {config.label}
                            </option>
                          ))}
                        </select>
                        <small>{POSTW90_MODULE_CONFIG[postw90Module]?.description}</small>
                      </label>
                      <div className="field-row field-row--postw90">
                        {(POSTW90_MODULE_CONFIG[postw90Module]?.fields || []).map((field) => (
                          <label className="field" key={`postw90-${field.key}`}>
                            <span>{field.label}</span>
                            <input
                              type={field.type}
                              step={field.step}
                              value={postw90Params[field.key] ?? ""}
                              onChange={(event) =>
                                setPostw90Params((prev) => ({
                                  ...prev,
                                  [field.key]: event.target.value,
                                }))
                              }
                              disabled={postw90Submitting}
                            />
                          </label>
                        ))}
                      </div>
                      {postw90Error && (
                        <div className="analysis-error">{postw90Error}</div>
                      )}
                      <button
                        className="primary"
                        type="button"
                        onClick={submitPostw90Job}
                        disabled={!canLaunchPostw90}
                      >
                        {postw90Submitting
                          ? "Launching..."
                          : postw90Module === "fermi_surface"
                          ? "Run wannier90.x plot"
                          : "Run postw90.x"}
                      </button>
                    </div>
                    <div>
                      <h3>Available modules</h3>
                      <div className="flag-list">
                        {Object.entries(POSTW90_MODULE_CONFIG).map(([key, config]) => (
                          <div className="flag-item" key={`postw90-module-${key}`}>
                            <span
                              className={`status ${
                                postw90Module === key ? "status--success" : "status--muted"
                              }`}
                            >
                              {config.label}
                            </span>
                            <span>{config.description}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="artifact-subtitle">Final centers and spreads</div>
                  {wannierFunctionPreview.length === 0 && wannierFunctions.length === 0 ? (
                    <div className="empty">
                      No final Wannier centers were parsed from wannier90.wout.
                    </div>
                  ) : (
                    <>
                      <div className="mini-table-wrap">
                        <table className="mini-table">
                          <thead>
                            <tr>
                              <th>WF</th>
                              <th>Center x</th>
                              <th>Center y</th>
                              <th>Center z</th>
                              <th>Spread</th>
                            </tr>
                          </thead>
                          <tbody>
                            {visibleWannierFunctions.map((item) => (
                              <tr key={`wf-${item.index}`}>
                                <td>{item.index}</td>
                                <td>{formatMetricValue(item.center_cartesian?.[0])}</td>
                                <td>{formatMetricValue(item.center_cartesian?.[1])}</td>
                                <td>{formatMetricValue(item.center_cartesian?.[2])}</td>
                                <td>{formatMetricValue(item.spread)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <div className="section-summary">
                        Showing{" "}
                        {showAllWannierFunctions
                          ? visibleWannierFunctions.length
                          : Math.min(
                              visibleWannierFunctions.length,
                              WANNIER_FUNCTION_PREVIEW_LIMIT
                            )}{" "}
                        of {wannierFunctionCount} Wannier functions. The metrics JSON keeps only a
                        compact preview; full rows are loaded on demand.
                      </div>
                      {wannierDetailsError && (
                        <div className="analysis-error">{wannierDetailsError}</div>
                      )}
                      {wannierFunctionCount > WANNIER_FUNCTION_PREVIEW_LIMIT && (
                        <div className="table-toggle">
                          <button
                            type="button"
                            className="ghost ghost--small"
                            onClick={toggleWannierFunctionTable}
                          >
                            {wannierDetailsStatus === "loading"
                              ? "Loading full Wannier table..."
                              : showAllWannierFunctions
                              ? "Show fewer Wannier functions"
                              : `Show all Wannier functions (${wannierFunctionCount})`}
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </>
              ) : (
                <>
                  <div className="metric-strip">
                    <div className="metric-box">
                      <div className="metric-label">Final total energy</div>
                      <div className="metric-value">
                        {formatMetricValue(vaspMetricsData.energy_summary?.final_total)}
                        <span>eV</span>
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Band gap</div>
                      <div className="metric-value">
                        {formatMetricValue(vaspMetricsData.electronic_summary?.band_gap)}
                        <span>eV</span>
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Max force</div>
                      <div className="metric-value">
                        {formatMetricValue(vaspMetricsData.force_stress_summary?.max_force)}
                        <span>eV/A</span>
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Space group</div>
                      <div className="metric-value metric-value--text">
                        {hdf5Spacegroup.international
                          ? `${hdf5Spacegroup.number} ${hdf5Spacegroup.international}`
                          : "-"}
                      </div>
                    </div>
                  </div>

                  <div className="detail-grid">
                    <div>
                      <div className="section-heading">
                        <h3>Quality checks</h3>
                        <span className={`status status--${hdf5QcOverview.level}`}>
                          {hdf5QcOverview.label}
                        </span>
                      </div>
                      <div className="section-summary">{hdf5QcOverview.summary}</div>
                      <div className="status-cluster">
                        <span className="status status--danger">
                          Errors {hdf5QcOverview.counts.error}
                        </span>
                        <span className="status status--warn">
                          Warnings {hdf5QcOverview.counts.warn}
                        </span>
                        <span className="status status--muted">
                          Info {hdf5QcOverview.counts.info}
                        </span>
                      </div>
                      <div className="kv">
                        <div>Finished cleanly</div>
                        <div>{formatBooleanMetric(vaspMetricsData.qc?.finished_cleanly)}</div>
                        <div>Electronic convergence</div>
                        <div>{formatBooleanMetric(vaspMetricsData.qc?.electronic_converged)}</div>
                        <div>Ionic convergence</div>
                        <div>{formatBooleanMetric(vaspMetricsData.qc?.ionic_converged)}</div>
                        <div>HDF5 parsed</div>
                        <div>{formatBooleanMetric(vaspMetricsData.inputs_summary?.hdf5_used)}</div>
                        <div>Max force / threshold</div>
                        <div>
                          {formatMetricValue(vaspMetricsData.qc?.max_force_eVA)} / {formatMetricValue(vaspMetricsData.qc?.force_threshold_eVA)} eV/A
                        </div>
                        <div>Max stress / threshold</div>
                        <div>
                          {formatMetricValue(vaspMetricsData.qc?.max_stress_kbar)} / {formatMetricValue(vaspMetricsData.qc?.stress_threshold_kbar)} kbar
                        </div>
                      </div>
                      <div className="artifact-subtitle">QC flags</div>
                      {hdf5QcFlags.length === 0 ? (
                        <div className="empty">No QC flags.</div>
                      ) : (
                        <div className="flag-list">
                          {hdf5QcFlags.map((flag, index) => (
                            <div className="flag-item" key={`${flag.code}-${index}`}>
                              <span className={`status status--${flag.severity === "error" ? "danger" : flag.severity === "warn" ? "warn" : "muted"}`}>
                                {flag.code}
                              </span>
                              <span>{flag.evidence}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <div>
                      <h3>Structure and postprocess</h3>
                      <div className="kv">
                        <div>System</div>
                        <div>{vaspMetricsData.inputs_summary?.system_name || "-"}</div>
                        <div>Atoms</div>
                        <div>{vaspMetricsData.inputs_summary?.num_atoms ?? "-"}</div>
                        <div>Volume</div>
                        <div>{formatMetricValue(vaspMetricsData.structure_summary?.volume)} A^3</div>
                        <div>Crystal system</div>
                        <div>{hdf5Spacegroup.crystal_system || "-"}</div>
                        <div>Primary task</div>
                        <div>{hdf5PluginSummary.primary_task_type || "-"}</div>
                        <div>Active plugins</div>
                        <div>
                          {hdf5PluginSummary.active_plugins?.length
                            ? hdf5PluginSummary.active_plugins.join(", ")
                            : "-"}
                        </div>
                        <div>Fermi level</div>
                        <div>{formatMetricValue(vaspMetricsData.electronic_summary?.efermi)} eV</div>
                        <div>Total magnetization</div>
                        <div>{formatMetricValue(vaspMetricsData.electronic_summary?.total_magnetization)}</div>
                        <div>High-symmetry lattice</div>
                        <div>{hdf5HighPath.bravais_lattice_extended || hdf5HighPath.bravais_lattice || "-"}</div>
                      </div>
                    </div>
                  </div>

                  <div className="artifact-subtitle">Electronic summary</div>
                  <div className="detail-grid">
                    <div className="section">
                      <strong>Band / DOS</strong>
                      <small>
                        Direct gap:{" "}
                        {hdf5BandDos.is_direct_gap === null || hdf5BandDos.is_direct_gap === undefined
                          ? "-"
                          : hdf5BandDos.is_direct_gap
                          ? "Yes"
                          : "No"}
                      </small>
                      <small>
                        VBM: {formatMetricValue(hdf5BandDos.vbm?.energy)} eV | CBM: {formatMetricValue(hdf5BandDos.cbm?.energy)} eV
                      </small>
                    </div>
                    <div className="section">
                      <strong>Near-Fermi contributions</strong>
                      <small>
                        Elements:{" "}
                        {hdf5BandDos.fermi_nearby_contributions?.elements?.length
                          ? hdf5BandDos.fermi_nearby_contributions.elements
                              .map((item) => item.label)
                              .join(", ")
                          : "-"}
                      </small>
                      <small>
                        Orbitals:{" "}
                        {hdf5BandDos.fermi_nearby_contributions?.orbitals?.length
                          ? hdf5BandDos.fermi_nearby_contributions.orbitals
                              .map((item) => item.label)
                              .join(", ")
                          : "-"}
                      </small>
                    </div>
                  </div>

                  <div className="artifact-subtitle">Generated plots</div>
                  {hdf5PlotItems.length === 0 ? (
                    <div className="empty">No HDF5 plots were generated.</div>
                  ) : (
                    <div className="thumb-grid thumb-grid--compact">
                      {hdf5PlotItems.map((item) => (
                        <figure className="thumb-card" key={item.key}>
                          <a href={item.src} target="_blank" rel="noreferrer">
                            <img src={item.src} alt={item.label} loading="lazy" />
                          </a>
                          <figcaption className="thumb-caption">
                            <span>{item.label}</span>
                          </figcaption>
                        </figure>
                      ))}
                    </div>
                  )}

                  <div className="artifact-subtitle">Structured outputs</div>
                  {hdf5ArtifactItems.length === 0 ? (
                    <div className="empty">No HDF5 structured outputs available.</div>
                  ) : (
                    <div className="artifact-list artifact-list--compact artifact-list--dense">
                      {hdf5ArtifactItems.map((artifact) => (
                        <a
                          key={artifact.key}
                          className="artifact artifact--compact"
                          href={artifact.href}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <span className="artifact-copy">
                            <span className="artifact-file">{artifact.label}</span>
                          </span>
                          <span className="arrow">Download</span>
                        </a>
                      ))}
                    </div>
                  )}
                </>
              )}
            </section>

            <section className="card vasp-log-card full-span">
              <div className="card__header">
                <h2>VASP live logs</h2>
                <span className={`pill pill--${vaspLogStatus}`}>
                  {vaspLogStatus}
                </span>
              </div>
              <div className="log" ref={vaspLogBoxRef}>
                {vaspLogLines.length === 0 ? (
                  <div className="empty">Waiting for VASP log stream...</div>
                ) : (
                  <pre>{vaspLogLines.join("\n")}</pre>
                )}
              </div>
            </section>

            <section className="card assistant-card full-span">
              <div className="card__header">
                <h2>VASP AI assistant</h2>
                <div className="analysis-actions">
                  <div className="analysis-model">
                    <span>Model</span>
                    <select
                      value={vaspAnalysisModel}
                      onChange={(event) => setVaspAnalysisModel(event.target.value)}
                      disabled={!canAnalyzeVasp || vaspAnalysisStatus === "loading"}
                    >
                      {VASP_ANALYSIS_MODELS.map((model) => (
                        <option key={model.value} value={model.value}>
                          {model.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <span className={`pill pill--analysis-${vaspAnalysisStatus}`}>
                    {vaspAnalysisStatus}
                  </span>
                  <button
                    className="ghost"
                    type="button"
                    onClick={runVaspAnalysis}
                    disabled={!canAnalyzeVasp || vaspAnalysisStatus === "loading"}
                  >
                    {vaspAnalysisStatus === "loading" ? "Analyzing..." : "Analyze"}
                  </button>
                </div>
              </div>
              {vaspAnalysisError && (
                <div className="analysis-error">{vaspAnalysisError}</div>
              )}
              <div className="assistant-section-title">Analysis</div>
              <div
                className="analysis-body"
                ref={vaspAnalysisBoxRef}
                onScroll={handleVaspAnalysisScroll}
              >
                {vaspAnalysisText ? (() => {
                  const { reasoning, answer } = splitReasoning(vaspAnalysisText);
                  return (
                    <>
                      {reasoning && (
                        <details className="reasoning-block">
                          <summary>Reasoning</summary>
                          <div className="reasoning-content">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {reasoning}
                            </ReactMarkdown>
                          </div>
                        </details>
                      )}
                      {answer ? (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {answer}
                        </ReactMarkdown>
                      ) : (
                        <div className="empty">Waiting for answer...</div>
                      )}
                    </>
                  );
                })() : (
                  <div className="empty">
                    {!vaspSupportsAi
                      ? "AI analysis is not available for this VASP mode."
                      : canAnalyzeVasp
                      ? "No VASP analysis yet. Click Analyze to generate."
                      : "VASP analysis is available after the run finishes and metrics are ready."}
                  </div>
                )}
              </div>
              <div className="assistant-section-title">Chat</div>
              {vaspChatError && <div className="analysis-error">{vaspChatError}</div>}
              <div
                className="chat-body"
                ref={vaspChatBoxRef}
                onScroll={handleVaspChatScroll}
              >
                {vaspChatMessages.length === 0 ? (
                  <div className="empty">
                    {!vaspSupportsAi
                      ? "Chat is not available for this VASP mode."
                      : canChatVasp
                      ? "No messages yet. Ask a follow-up question."
                      : "Chat is available after VASP analysis completes."}
                  </div>
                ) : (
                  vaspChatMessages.map((msg, index) => (
                    <div
                      key={msg.id || `${msg.role}-${index}`}
                      className={`chat-message chat-${msg.role}`}
                    >
                      <div className="chat-role">
                        {msg.role === "assistant" ? "Assistant" : "You"}
                      </div>
                      <div className="chat-content">
                        {msg.role === "assistant" ? (() => {
                          const { reasoning, answer } = splitReasoning(msg.content);
                          return (
                            <>
                              {reasoning && (
                                <details className="reasoning-block">
                                  <summary>Reasoning</summary>
                                  <div className="reasoning-content">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                      {reasoning}
                                    </ReactMarkdown>
                                  </div>
                                </details>
                              )}
                              {answer ? (
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                  {answer}
                                </ReactMarkdown>
                              ) : (
                                <div className="empty">Waiting for answer...</div>
                              )}
                            </>
                          );
                        })() : (
                          <div>{msg.content}</div>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
              <div className="chat-input">
                <textarea
                  rows="3"
                  placeholder={
                    !vaspSupportsAi
                      ? "Chat is not available for this VASP mode."
                      : canChatVasp
                      ? "Ask a follow-up question about the VASP analysis..."
                      : "Run VASP analysis first to enable chat."
                  }
                  value={vaspChatInput}
                  onChange={(event) => setVaspChatInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      if (canChatVasp && vaspChatStatus !== "loading") {
                        sendVaspChat();
                      }
                    }
                  }}
                  disabled={!canChatVasp || vaspChatStatus === "loading"}
                />
                <button
                  className="primary"
                  type="button"
                  onClick={sendVaspChat}
                  disabled={!canChatVasp || vaspChatStatus === "loading"}
                >
                  {vaspChatStatus === "loading" ? "Sending..." : "Send"}
                </button>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

