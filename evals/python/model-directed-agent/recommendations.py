"""Smash burger recommendation logic.

This module exposes a single tool function, `recommend_smash_burgers`, that the
chat agent can call. It returns a curated list of smash burger spots for a given
city. For well-known cities we return real, popular smash burger joints. For any
other city we fall back to a generic set of suggestions so the agent always has
something helpful to say.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Curated smash burger spots for a handful of popular cities.
# Keys are normalized (lowercase, stripped) city names.
_CITY_RECOMMENDATIONS: Dict[str, List[Dict[str, str]]] = {
    "new york": [
        {"name": "Hamburger America", "why": "Classic smash-style single patties, minimalist toppings."},
        {"name": "7th Street Burger", "why": "Cult-favorite thin, crispy smashed patties with American cheese."},
        {"name": "Smashed", "why": "No-frills griddled smash burgers with a great crust."},
    ],
    "los angeles": [
        {"name": "The Win~Dow", "why": "Crispy-edged smash burgers from a walk-up window in Venice."},
        {"name": "Burgers Never Say Die", "why": "Silver Lake smash spot with a devoted following."},
        {"name": "For The Win", "why": "Thin, lacy-edged smash patties done right."},
    ],
    "chicago": [
        {"name": "Small Cheval", "why": "Streamlined smash burger from the Au Cheval team."},
        {"name": "Redhot Ranch", "why": "Griddled smashed patties alongside Chicago-style dogs."},
        {"name": "Butcher & The Burger", "why": "Custom smash burgers with house seasonings."},
    ],
    "austin": [
        {"name": "Sammie's", "why": "Retro-diner smash burgers with crispy edges."},
        {"name": "P. Terry's", "why": "Local chain doing clean, fresh smash-style burgers."},
        {"name": "Bureau de Poste", "why": "French-influenced smash burger that's a local favorite."},
    ],
    "san francisco": [
        {"name": "Causwells", "why": "The 'Americana' smash burger is a Bay Area staple."},
        {"name": "Marla Bakery / Popup smash spots", "why": "Rotating smash burger pop-ups worth chasing."},
        {"name": "Wesburger", "why": "Griddle-smashed patties with solid house sauce."},
    ],
    "london": [
        {"name": "Bleecker Burger", "why": "Famous for its crusty, smashed-to-order patties."},
        {"name": "Patty & Bun", "why": "Smashed patties with a cult 'Ari Gold' burger."},
        {"name": "Black Bear Burger", "why": "High-quality beef, proper smashed crust."},
    ],
}

# Generic fallback used when we don't have a curated list for the city.
_GENERIC_RECOMMENDATIONS: List[Dict[str, str]] = [
    {"name": "A local smash-focused burger joint", "why": "Search for spots advertising 'smash burgers' or 'griddle burgers'."},
    {"name": "A popular gastropub or diner", "why": "Many serve crispy-edged smash-style patties."},
    {"name": "Food-truck / pop-up smash vendors", "why": "Often some of the best smash burgers in any city."},
]


def recommend_smash_burgers(city: str, limit: int = 3) -> Dict[str, Any]:
    """Return smash burger recommendations for the given city.

    Args:
        city: The city to recommend smash burger restaurants in.
        limit: Maximum number of recommendations to return.

    Returns:
        A dict with the resolved city, whether the list was curated, and the
        list of recommendations (each with a name and a short reason).
    """
    if not isinstance(city, str):
        raise TypeError("city must be a string")
    normalized = city.strip().lower()
    curated = normalized in _CITY_RECOMMENDATIONS

    if curated:
        picks = _CITY_RECOMMENDATIONS[normalized]
    else:
        picks = _GENERIC_RECOMMENDATIONS

    limit = max(1, min(limit, len(picks)))

    return {
        "city": city.strip() if city else "",
        "curated": curated,
        "recommendations": picks[:limit],
    }
