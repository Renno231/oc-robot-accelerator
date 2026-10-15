"""Task-oriented recipes. OC's native assembler remains the authority on legality."""
from copy import deepcopy

# Pinned OC 1.8.9a native driver tiers and Template.complexity rules.
# This early check covers the builder recipe vocabulary; native assembly is
# still mandatory for every recipe, including custom components/settings.
TIERS = {'inventoryupgrade': 0, 'inventorycontrollerupgrade': 1,
         'angelupgrade': 1, 'hoverupgrade2': 1, 'experienceupgrade': 2,
         'batteryupgrade1': 0, 'batteryupgrade2': 1, 'batteryupgrade3': 2,
         'ram6': 2, 'hdd3': 2, 'upgradecontainer1': 0,
         'upgradecontainer2': 1, 'upgradecontainer3': 2}

def preflight_standard_builder_recipe(recipe):
    if recipe['tier'] != 3 or recipe['cpu'] != 'cpu3':
        return  # Other tier/CPU combinations require native template validation.
    parts = recipe.get('memory', []) + recipe.get('cards', []) + recipe.get('storage', []) + recipe.get('upgrades', [])
    names = [p if isinstance(p,str) else p['item'] for p in parts]
    containers = [p['item'] for p in recipe.get('containers', [])]
    if any(n not in TIERS for n in names + containers):
        return  # Never invent a tier/cost for a custom native component.
    used = sum(TIERS[n]+1 for n in names) + sum(2*(TIERS[n]+1) for n in containers)
    if used > 32:
        raise ValueError('native survival assembly complexity exceeded: %d/32' % used)
    return used

BUILDER_MAX = {
    'tier': 3, 'cpu': 'cpu3', 'memory': ['ram6', 'ram6'], 'cards': [],
    'storage': ['hdd3'], 'bootDrive': 0,
    'upgrades': ['inventoryupgrade'] * 4 + [
        'inventorycontrollerupgrade', 'angelupgrade', 'hoverupgrade2',
        {'item': 'experienceupgrade', 'level': 30}, 'batteryupgrade3'],
    'containers': [
        {'item': 'upgradecontainer3', 'component': 'batteryupgrade3'},
    ],
}

def resolve_profile(name):
    if name != 'builder-max':
        raise ValueError('unknown native hardware profile: ' + str(name))
    result = deepcopy(BUILDER_MAX)
    preflight_standard_builder_recipe(result)
    return result
