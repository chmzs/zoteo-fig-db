"""出版商家族规则单一事实源：batch_master(调度/QC) 与 adapters(提取路由) 共用。"""

# 刊名兜底规则（publisher 字段大面积为空时用；元组顺序即优先级）
JOURNAL_RULES = [
    ("agu", ["geophysical research letters", "journal of geophysical research", "water resources research",
             "earth's future", "paleoceanography", "global biogeochemical", "tectonics", "space weather",
             "radio science", "geochemistry, geophysics", "reviews of geophysics", "earth and space science",
             "agu advances", "james", "space science reviews", "geohealth", "agupubs"]),
    ("nature", ["nature communications", "nature geoscience", "nature climate change", "nature ecology & evolution",
                "nature sustainability", "nature food", "nature water", "nature astronomy", "nature geophysics",
                "npj climate", "communications earth", "communications environment", "communications biology",
                "scientific reports", "nature mechanical", "nature energy", "nature nanotechnology"]),
    ("aaas", ["science advances", "science robotics", "science immunology", "science translational medicine"]),
    ("pnas", ["proceedings of the national academy"]),
    ("elsevier", ["quaternary science reviews", "quaternary international", "quaternary geochronology",
                  "palaeogeography", "catena", "global and planetary change", "journal of hydrology",
                  "remote sensing of environment", "earth-science reviews", "earth and planetary science letters",
                  "geochimica et cosmochimica", "chemical geology", "sedimentary geology", "marine geology",
                  "ore geology reviews", "journal of asian earth sciences", "journal of archaeological science",
                  "journal of human evolution", "deep-sea research", "ecological indicators", "ecological modelling",
                  "environmental pollution", "chemosphere", "science of the total environment", "environment international",
                  "journal of environmental management", "advances in water resources", "water research",
                  "anthropocene", "marine pollution bulletin", "palaeoworld", "journal of arid environments",
                  "journal of structural geology", "journal of volcanology", "review of palaeobotany",
                  "quaternary research", "earth-science", "journal of contamination", "ecological complexity",
                  "environmental development", "current opinion in environmental", "groundwater", "heliyon"]),
    ("springer", ["climate dynamics", "journal of paleolimnology", "climatic change", "vegetation history",
                  "natural hazards", "paleontology journal", "theoretical and applied climatology",
                  "geo-marine letters", "biodiversity and conservation", "plant ecology", "aquatic ecology",
                  "sustainability science", "climate research", "polar biology", "international journal of earth sciences",
                  "method and theory", "past atmospheric research", "journal of atmospheric chemistry",
                  "advances in atmospheric sciences", "climatic change"]),
    ("wiley", ["global change biology", "ecology letters", "ecological applications", "conservation biology",
               "journal of biogeography", "functional ecology", "methods in ecology and evolution",
               "global ecology and biogeography", "ecography", "limnology and oceanography",
               "the holocene", "journal of quaternary science", "ice ages past and environments",
               "molecular ecology", "new phytologist", "conservation science", "diversity and distributions",
               "ecological monographs", "soil science society", "crop science", "geographical analysis",
               "quarterly journal of the royal meteorological", "international journal of climatology",
               "weather and forecasting", "wildlife monographs", "fish and fisheries", "aquatic conservation",
               "landscape ecology", "ecological solutions", "restoration ecology", "conservation physiology"]),
    ("copernicus", ["climate of the past", "atmospheric chemistry and physics", "biogeosciences",
                    "the cryosphere", "earth system science data", "hydrology and earth system",
                    "natural hazards and earth", "geoscientific model development", "nonlinear processes",
                    "ocean science", "solid earth", "elementa", "egquaria", "anthropocene coasts",
                    "open atmospheres", "soundings", "journal of micropalaeontology", "quaternary of the anthropocene"]),
    ("iop", ["environmental research letters", "environmental research communications", "new journal of physics",
             "planetary science journal", "research in astronomy", "chinese physics", "stacks of physics",
             "environmental research express"]),
    ("cambridge", ["radiocarbon", "journal of fluid mechanics", "polar record", "annals of exploration",
                   "quarterly reviews of biology", "prehistory", "antiquity"]),
    ("tandf", ["annals of the american association", "progress in physical geography", "professional geographer",
               "arctic, antarctic and alpine research", "journal of maps", "geo-cartography", "environment and history",
               "geojournal", "international journal of geographical", "physical geography", "annals of the association" ]),
    ("sage", ["anthropocene review", "sage open", "evolutionary bioinformatics", "geographical review"]),
    ("oup", ["bioscience", "annals of botany", "glycobiology", "tree physiology", "jhered", "iovs",
             "mutation research", "fems"]),
    ("acs", ["environmental science & technology", "environmental science and technology", "acs earth"]),
    ("gsw", ["geosphere", "lithosphere", "gsa today", "geological society of america", "gssa bulletin"]),
    ("mdpi", ["remote sensing", "sustainability", "atmosphere", "forests", "minerals", "geosciences",
              "hydrology", "agrochemicals", "international journal of environmental research",
              "land", "water", "climate", "plants", "fire", "quaternary geochronology"]),
    ("frontiers", ["frontiers in", "frontiers of"]),
    ("uchicago", ["international journal of plant sciences", "botanical gazette", "quarterly review of biology"]),
]

EXACT_FAMILY = {
    "nature": "nature", "science": "aaas", "pnas": "pnas",
    "geology": "gsw", "holocene": "wiley", "catena": "elsevier",
    "ecography": "wiley", "elementa": "copernicus", "bioscience": "oup",
}

def _journal_family(jl):
    if jl.strip() in EXACT_FAMILY:
        return EXACT_FAMILY[jl.strip()]
    for fam, keys in JOURNAL_RULES:
        for k in keys:
            if k in jl:
                return fam
    return None



def journal_family(journal):
    """公开入口：刊名 -> 家族（小写归一）；无命中返回 None。"""
    return _journal_family((journal or "").lower())
