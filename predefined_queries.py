"""Shared predefined questions used by Streamlit and backend startup validation."""

FARMER_TYPES = (
    "சிறு / குறு விவசாயி (<= 5 ஏக்கர்)",
    "பெரிய விவசாயி (> 5 ஏக்கர்)",
    "மகளிர் விவசாயக் குழு",
)

CROP_INTERESTS = (
    "நெல் (Paddy)",
    "தோட்டக்கலை பயிர்கள் (Horticulture)",
    "பருத்தி மற்றும் தானியங்கள்",
)

QUICK_QUERIES = {
    "pani_pipe": "Pani Pipe AWD மற்றும் நுண்ணீர் பாசன திட்டம் என்றால் என்ன?",
    "kalaignar": "கலைஞரின் அனைத்து கிராம ஒருங்கிணைந்த வேளாண் வளர்ச்சி திட்டம் விவரங்கள்",
    "custom_hiring": "விவசாய இயந்திர வாடகை மையம் (CHC) அமைப்பதற்கான மானியம் என்ன?",
    "power_and_insurance": (
        "விவசாய இலவச மின் இணைப்பு வழங்கும் தட்கல் திட்டம் மற்றும் PMFBY "
        "பிரதம மந்திரி பயிர் காப்பீடு திட்டம் விவரங்கள் மற்றும் விண்ணப்பிக்கும் முறை யாவை?"
    ),
}


def eligibility_query(farmer_type: str, crop_interest: str) -> str:
    return (
        f"{farmer_type} பிரிவினருக்கு {crop_interest} பயிரிட தமிழக அரசு "
        "வழங்கும் மானியங்கள் மற்றும் நலத்திட்டங்கள் யாவை?"
    )


_BACKEND_QUERIES = (
    "Pani Pipe AWD என்றால் என்ன?",
    "நெல் பாசன வழிகாட்டல்",
    "SRI square planting முறை பற்றி கூறு",
    "list tamilnadu agriculture schemes",
    "முக்கிய 5 அரசு திட்டங்கள்",
    "NAIS திட்டம் பற்றி கூறு",
    "Minikit Programme for Rice",
    "இயந்திர வாடகை மையம்",
    "வாடகை மையம் (CHC), டிராக்டர் & நடவு இயந்திர மானியம்",
    "விவசாய மின் இணைப்பு பெறுவதற்கான விதிமுறைகள் என்ன?",
    "இலவச மின் இணைப்பு விதி",
)

PREWARM_QUERIES = _BACKEND_QUERIES

PREDEFINED_QUERIES = tuple(dict.fromkeys((
    *_BACKEND_QUERIES,
    *QUICK_QUERIES.values(),
    *(
        eligibility_query(farmer_type, crop_interest)
        for farmer_type in FARMER_TYPES
        for crop_interest in CROP_INTERESTS
    ),
)))
