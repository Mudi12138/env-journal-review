# Environmental top-journal taxonomy v1 (for LLM classification)

Derived from the 51-topic BERTopic run on 40,202 papers (ES&T, Water Research, Nature
Climate Change, Nature Geoscience, Nature Sustainability, One Earth, Nature Water,
2015–2026), then revised by hand: clusters that were text-similarity artefacts were split,
subject areas the clustering scattered (adsorption, ecotoxicology, trace metals, phosphorus
recovery, circular economy) were restored, and the one method-led cluster was moved to a
separate axis.

## How to apply (for the labelling model)

1. Assign **1–3 SUBJECT labels** from Axis 1, most central first. Use a second or third
   label only when the paper genuinely sits in two areas (e.g. PFAS removal by adsorption
   → `A4` + `C3`).
2. Assign **0–2 APPROACH tags** from Axis 2. These are orthogonal: they never replace a
   subject label.
3. `Z1` (non-research) and `Z2` (other) are last resorts, never combined with a subject label.
4. Judge by what is *studied*, not by the journal or by which words appear most often.
5. If the paper is a review of an area, label the area, not "review" (use approach tag `M7`).

## Axis 1 — Subject (60 classes, 10 groups)

### A. Organic contaminants and emerging pollutants
| Code | Label | Covers | Not this |
|---|---|---|---|
| A1 | Non-target screening and environmental analytical chemistry | Suspect/non-target screening, HRMS workflows, identification and prioritisation of unknown organics, passive sampling | A study that uses routine analysis to answer a fate question → label by the contaminant |
| A2 | Pharmaceuticals and personal care products | PPCPs, antibiotics as chemicals, hormones from drugs, their occurrence/fate | Antibiotic *resistance* → E3 |
| A3 | Pesticides and agrochemicals | Insecticides, herbicides, fungicides, biocides: occurrence, fate, transport | Fertiliser nutrients → F3 |
| A4 | PFAS | Per-/polyfluoroalkyl substances: sources, fate, exposure, destruction, removal | — |
| A5 | Micro- and nanoplastics | Plastic particles and fibres, ageing, transport, analysis | Plastic waste management → I4 |
| A6 | PAHs and petroleum hydrocarbons | PAHs, oil spills, combustion-derived hydrocarbons | Brown carbon optics → G2 |
| A7 | Legacy POPs, flame retardants and industrial chemicals | PCBs, PBDEs, organophosphate esters, chlorinated solvents as contaminants, siloxanes | In-situ dechlorination technology → B6 |

### B. Inorganic contaminants, geochemistry and remediation
| Code | Label | Covers | Not this |
|---|---|---|---|
| B1 | Arsenic | Groundwater/soil arsenic: speciation, mobilisation, removal | — |
| B2 | Mercury and isotope tracing | Hg/MeHg cycling, methylation, stable-isotope source tracing (also other metal isotope tracing) | — |
| B3 | Trace metals and metalloids | Cd, Pb, Cr, Cu, Zn, Ni, U: speciation, mobility, toxicity, removal | Metals as critical raw materials → I4 |
| B4 | Mineral–water interfaces and Fe/Mn redox | Iron oxides, clays, sorption/redox at mineral surfaces, colloids | Engineered sorbents → C3 |
| B5 | Soil, sediment and site contamination | Contaminated land and sediments, plant uptake, soil pollution surveys | Soil carbon cycling → H4 |
| B6 | Remediation technologies for subsurface contamination | ZVI/nZVI, in-situ chemical/biological remediation, natural attenuation, monitored dechlorination | Ex-situ water treatment → group C |

| B7 | Radioactivity and radionuclides in the environment | Environmental radioactivity and radiological risk: fallout and accident releases (Fukushima, Chernobyl), radioactive waste and spent fuel, radon, tritium, Cs-137/I-129/Pu, radionuclide migration and decontamination, dose assessment | uranium or thorium studied as a chemical contaminant or sorbate without radiological framing → B3 |

### C. Water and wastewater treatment processes
| Code | Label | Covers | Not this |
|---|---|---|---|
| C1 | Advanced oxidation and catalytic degradation | Fenton, persulfate, ozonation, photo/electrocatalysis for pollutant destruction | Atmospheric catalysis → G6 |
| C2 | Disinfection and disinfection by-products | Chlorine/chloramine/UV/ozone disinfection, DBP formation, control and toxicity | Pathogen ecology/risk → E2 |
| C3 | Adsorption, ion exchange and sorbent materials | Activated carbon, biochar as sorbent, MOFs, resins, engineered sorbents for removal | Natural mineral sorption → B4 |
| C4 | Pressure-driven membranes and fouling | NF, RO, UF, MF: materials, rejection, fouling, desalination by RO | MBR → D6 |
| C5 | Thermal and emerging desalination | Membrane distillation, forward osmosis, solar/thermal desalination, brine management | — |
| C6 | Electrochemical treatment and ion-selective separation | Capacitive deionisation, electrodialysis, electrocoagulation, electrochemical sensors excluded | Microbial electrochemistry → D4 |
| C7 | Conventional treatment trains and drinking-water production | Coagulation, sedimentation, filtration, softening, plant operation and optimisation | Distribution-system water quality → E1 |

### D. Biological treatment and resource recovery
| Code | Label | Covers | Not this |
|---|---|---|---|
| D1 | Biological nitrogen removal | Nitrification, denitrification, anammox, comammox, N2O from reactors | Nitrogen cycling in natural waters → F5 |
| D2 | Phosphorus removal and recovery | EBPR, struvite/vivianite, phosphate recovery from sludge and streams | Phosphorus in lakes → F1/F3 |
| D3 | Anaerobic digestion and bioenergy | Digesters, biogas, co-digestion, fermentation for chemicals | — |
| D4 | Microbial electrochemical systems | MFC, MEC, microbial electrosynthesis, electroactive biofilms | — |
| D5 | Sludge treatment, properties and dewatering | Activated sludge physico-chemistry, EPS, conditioning, dewatering, sludge disposal | — |
| D6 | Membrane bioreactors and biofilm reactors | MBR, MABR, granular sludge reactors, biofilm process engineering | Drinking-water biofilms → E1 |
| D7 | Algal and algal–bacterial systems | Microalgae for nutrient removal, algal biomass, photobioreactors | Harmful algal blooms in lakes → F1 |
| D8 | Nutrient and resource recovery from waste streams | Ammonia recovery, urine/source separation, water reuse as resource, energy-neutral plants | — |

### E. Drinking water, distribution and environmental health microbiology
| Code | Label | Covers | Not this |
|---|---|---|---|
| E1 | Distribution systems and premise plumbing | Biofilms, disinfectant residual, biological stability, lead/copper corrosion, tap water quality | Treatment-plant processes → C7 |
| E2 | Waterborne pathogens and microbial risk | Faecal indicators, enteric viruses/protozoa, QMRA, wastewater-based epidemiology | ARGs → E3 |
| E3 | Antimicrobial resistance in the environment | Resistomes, resistant bacteria, ARG transport and removal | Antibiotics as chemicals → A2 |

### F. Catchments, inland and coastal waters
| Code | Label | Covers | Not this |
|---|---|---|---|
| F1 | Eutrophication and harmful algal blooms | Cyanobacteria, cyanotoxins, lake/reservoir trophic state, bloom management | Algal cultivation → D7 |
| F2 | Dissolved organic matter and photochemistry | DOM composition and reactivity, photoproduced reactive species, optical properties | DOM as membrane foulant → C4 |
| F3 | Catchment nutrients, hydrology and transport | Nitrate/phosphorus export, isotope tracing, monitoring networks, stormwater quality | Urban drainage infrastructure → I5 |
| F4 | Greenhouse gas fluxes from inland waters | CH4/CO2/N2O from rivers, lakes, reservoirs, sediments | Oil-and-gas methane → G5 |
| F5 | Microbial ecology and biogeochemistry of natural waters | Nitrogen/sulfur/carbon cycling microbes in rivers, groundwater, sediments, wetlands | Engineered reactors → group D |

### G. Atmosphere and air quality
| Code | Label | Covers | Not this |
|---|---|---|---|
| G1 | Atmospheric chemistry and aerosol formation | SOA, gas-phase oxidation, ozone/VOC chemistry, new particle formation | Health effects → G4 |
| G2 | Carbonaceous and light-absorbing aerosol | Black/brown carbon, biomass-burning aerosol, optical properties | — |
| G3 | Air quality measurement, source apportionment and modelling | Monitoring networks, mobile/low-cost sensing, CTM/satellite estimation, indoor air | Exposure–health association → G4 |
| G4 | Air pollution exposure and health | Epidemiology, oxidative potential, dose, mortality/morbidity burden, personal exposure | — |
| G5 | Methane and GHG emissions from energy and waste systems | Oil/gas methane, landfill and agricultural emissions, inventories, leak detection | Aquatic fluxes → F4 |
| G6 | Air pollution control technology | NH3-SCR, VOC catalytic oxidation, flue gas treatment, vehicle after-treatment | Water-phase catalysis → C1 |

### H. Climate, Earth system and ecosystems
| Code | Label | Covers | Not this |
|---|---|---|---|
| H1 | Climate variability, palaeoclimate and circulation | ENSO, AMOC, monsoon, ice cores, proxy records, cryosphere and sea level | Policy scenarios → I1 |
| H2 | Ocean warming, acidification and marine ecosystems | Ocean carbon uptake, marine biogeochemistry and ecology under change | Marine plastic → A5 |
| H3 | Terrestrial ecosystems, vegetation and drought | Productivity, forests, drought, land–atmosphere feedbacks, wildfire ecology | Land-use policy → I2 |
| H4 | Soil carbon, permafrost and the land carbon cycle | Soil C/N stocks, permafrost thaw, terrestrial carbon sinks | Soil contamination → B5 |
| H5 | Solid Earth and geology | Tectonics, mantle, seismicity, volcanism, geomorphology | — |
| H6 | Carbon dioxide removal and geological storage | Mineral carbonation, CCS, enhanced weathering, ocean alkalinity enhancement | Industrial decarbonisation → I3 |

| H7 | Planetary and extraterrestrial science | The Moon, Mars, Venus, icy moons, asteroids and meteorites, the early solar system, planetary atmospheres, surfaces and interiors, astrobiology and planetary missions | Earth's own solid-earth geology → H5; Earth's atmosphere → group G |

### I. Sustainability, systems and policy
| Code | Label | Covers | Not this |
|---|---|---|---|
| I1 | Climate mitigation policy and emission scenarios | Targets, pathways, carbon budgets, IAMs, climate governance and behaviour | Technology LCA → I3 |
| I2 | Land use, food systems and biodiversity | Agriculture, diets, land-system change, conservation, ecosystem services | Ecosystem ecology → H3 |
| I3 | Energy transition, LCA and industrial decarbonisation | Life-cycle assessment, renewables, EVs, hydrogen, sectoral decarbonisation, material flows | — |
| I4 | Circular economy, waste and critical materials | Recycling, e-waste, batteries, plastics-waste management, secondary raw materials | Plastic particles in the environment → A5 |
| I5 | Urban water systems and sanitation | Sewers, drainage, decentralised systems, sanitation access, infrastructure planning and asset management | Catchment hydrology → F3 |
| I6 | Water resources, scarcity and footprints | Groundwater depletion, virtual water, water footprints, allocation, reuse policy | — |
| I7 | Climate impacts, adaptation, risk and equity | Impacts on people/economies, adaptation, vulnerability, migration, environmental justice | Physical climate dynamics → H1 |

### J. Exposure, toxicology and materials in the environment
| Code | Label | Covers | Not this |
|---|---|---|---|
| J1 | Ecotoxicology and effect-based assessment | Whole-organism and in-vitro toxicity, bioassays, endocrine effects, mixture toxicity, species sensitivity | Human epidemiology → J3 |
| J2 | Engineered nanomaterials in the environment | Fate, transformation, bioaccumulation and effects of ENMs | Nanomaterials as sorbents/catalysts → C1/C3 |
| J3 | Human exposure and biomonitoring | Internal dose, biomonitoring, consumer products, dietary/indoor exposure pathways | Air-pollution epidemiology → G4 |

### Z. Catch-alls
| Code | Label | Use when |
|---|---|---|
| Z1 | Non-research content | Editorial, comment, news, correction, retraction, book review, front matter |
| Z2 | Other / does not fit | Genuinely outside every class above — record the suggested new class in a note |

## Axis 2 — Approach tags (optional, 0–2)

| Code | Tag | Meaning |
|---|---|---|
| M1 | Field observation / monitoring | Environmental sampling campaigns, observational networks |
| M2 | Laboratory experiment | Bench/pilot controlled experiments |
| M3 | Process/engineering development | New material, reactor or treatment configuration |
| M4 | Mechanistic / molecular characterisation | Spectroscopy, isotopes, omics, DFT, kinetics |
| M5 | Numerical modelling and simulation | Process, hydrological, atmospheric, Earth-system, techno-economic models |
| M6 | Machine learning and data science | ML/DL models, large-scale data mining, sensing analytics |
| M7 | Review / synthesis / meta-analysis | Reviews, systematic reviews, meta-analyses, perspectives on a field |
| M8 | Assessment and policy analysis | LCA, risk assessment, scenario and policy evaluation |

## What changed relative to the BERTopic output, and why

| Change | Reason |
|---|---|
| T0 (4,276 papers) split into A1, A2, A3, A7, and part to J1 | It was a catch-all: screening methods, pesticides, flame retardants, EDCs and 360 ecotoxicology papers in one cluster |
| T2 (1,856) split into I1, I2, I7 | Climate policy, land/food systems and adaptation are separate literatures merged by shared vocabulary |
| Added C3 Adsorption and sorbent materials | 952 title matches were scattered across mineral, PFAS and membrane clusters — the clustering follows the material, not the process |
| Added J1 Ecotoxicology | 499 papers, 360 of them inside T0 |
| Added B3 Trace metals, B5 Soil/sediment contamination | 430 and 95 papers with no home |
| Added D2 Phosphorus recovery, I4 Circular economy | 136 and 111 papers; I4 existed as its own topic in the 49-topic run and was merged away at 51 |
| Added C7 Conventional treatment, E1 extended to lead/corrosion, G3 extended to indoor air, I7 covers environmental justice | Small but real areas with no cluster of their own |
| T38 (ML for water) moved to Axis 2 (M6) | It clustered by method, not subject; keeping it on Axis 1 would force a false choice for any paper that uses ML on another topic |
| T23/T28/T37 reorganised into G3 (measurement/modelling) and G4 (exposure/health) | The three clusters overlapped; the defensible boundary is measurement vs health outcome |
| Membrane clusters (T25/T33/T42/T48) reorganised into C4, C5, D6 | Clusters split by membrane type; the useful boundary is driving force and whether biology is integral |

## Known judgement calls (challengeable)

- **DOM**: F2 merges the composition cluster (T20) and the photochemistry cluster (T36).
  They are separable, but the boundary confused even the clustering, and a labelling model
  would likely fail it.
- **Biochar** sits in C3 when used as a sorbent and in B4/H4 when studied as environmental
  carbon. The first label should follow the paper's purpose.
- **MBR** is placed with biological processes (D6) rather than membranes (C4).
- **Desalination** is split by driving force: RO in C4, MD/FO/thermal in C5, electrochemical in C6.
- **I2 vs H3** (land-use policy vs ecosystem ecology) is the least crisp boundary in the scheme.

## Patch 2026-09-21

B7 and H7 were added after the full run: the Z2 bucket showed 47 environmental-radioactivity papers and 25 planetary-science papers with nowhere to go, and both are recurring subjects in Nature Geoscience and ES&T rather than one-off strays. Papers that could belong to either class were re-asked; every other paper kept its first-pass class.
