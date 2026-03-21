"""
Seed initial — sommets français et alpins pour la mer de nuage.

Données générées via Overpass API (OpenStreetMap) le 2026-03-21,
complétées manuellement pour les massifs des Vosges et du Massif Central.

Usage :
    python -m app.db.seed

Prérequis :
    docker compose -f ../infra/docker-compose.dev.yml up -d
    alembic upgrade head
"""

import asyncio
import logging

from sqlalchemy import text

from app.db.session import async_session_maker, engine
from app.models.peak import Peak

logger = logging.getLogger(__name__)

PEAKS = [
    # Alpes — hauts sommets
    {
        "id": "95b3d052-884a-59f4-8509-5e4869f0b468",
        "name": "Mont Blanc",
        "slug": "mont-blanc",
        "lat": 45.832706,
        "lng": 6.865171,
        "altitude": 4807,
    },
    {
        "id": "da75b220-fa6a-5ae4-9c5d-d072ccdba20e",
        "name": "Mont Maudit",
        "slug": "mont-maudit",
        "lat": 45.847439,
        "lng": 6.875986,
        "altitude": 4465,
    },
    {
        "id": "cd8803e9-8a7f-5421-90b9-88c2b092cdc4",
        "name": "Dôme du Goûter",
        "slug": "dome-du-gouter",
        "lat": 45.842581,
        "lng": 6.843473,
        "altitude": 4304,
    },
    {
        "id": "aaf76153-0b6b-5473-b442-7ca9595b06b3",
        "name": "Mont Blanc du Tacul",
        "slug": "mont-blanc-du-tacul",
        "lat": 45.856586,
        "lng": 6.88852,
        "altitude": 4248,
    },
    {
        "id": "ffe045d4-ec07-5a89-a6b2-4d9180b0a378",
        "name": "Grandes Jorasses",
        "slug": "grandes-jorasses",
        "lat": 45.868156,
        "lng": 6.988983,
        "altitude": 4208,
    },
    {
        "id": "ab39239f-7610-5b37-be5b-1ac18eef5d81",
        "name": "Aiguille Verte",
        "slug": "aiguille-verte",
        "lat": 45.93459,
        "lng": 6.970019,
        "altitude": 4121,
    },
    {
        "id": "28198ec5-7534-5522-a9a7-e97f09570997",
        "name": "Aiguille de Bionnassay",
        "slug": "aiguille-de-bionnassay",
        "lat": 45.836054,
        "lng": 6.818674,
        "altitude": 4052,
    },
    {
        "id": "c274e389-e0c5-5250-92b4-733e7fa4bfbc",
        "name": "Dent du Géant",
        "slug": "dent-du-geant",
        "lat": 45.861898,
        "lng": 6.951899,
        "altitude": 4013,
    },
    {
        "id": "15dbb08d-7217-56eb-98d5-1b3559fc773e",
        "name": "Les Droites",
        "slug": "les-droites",
        "lat": 45.930684,
        "lng": 6.989306,
        "altitude": 4000,
    },
    {
        "id": "5f84f631-3c18-53ad-9589-43cc6244086e",
        "name": "Grand Paradis",
        "slug": "grand-paradis",
        "lat": 45.517819,
        "lng": 7.267201,
        "altitude": 4061,
    },
    {
        "id": "086b0711-47d7-5c28-872c-3b9c0f5bf3f4",
        "name": "Aiguille du Midi",
        "slug": "aiguille-du-midi",
        "lat": 45.878704,
        "lng": 6.887551,
        "altitude": 3842,
    },
    {
        "id": "773baa13-3314-518b-87f8-7b10cae86b6a",
        "name": "Aiguille du Goûter",
        "slug": "aiguille-du-gouter",
        "lat": 45.85095,
        "lng": 6.831238,
        "altitude": 3863,
    },
    {
        "id": "9c31c51c-58fd-5743-8598-7d03a9a17c28",
        "name": "Les Courtes",
        "slug": "les-courtes",
        "lat": 45.92743,
        "lng": 7.003213,
        "altitude": 3856,
    },
    {
        "id": "b112611a-ab4b-56a7-bd43-894696c5d19b",
        "name": "Aiguille d'Argentière",
        "slug": "aiguille-dargentiere",
        "lat": 45.959559,
        "lng": 7.019973,
        "altitude": 3901,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890abc",
        "name": "Grande Casse",
        "slug": "grande-casse",
        "lat": 45.3894,
        "lng": 6.8467,
        "altitude": 3855,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890abe",
        "name": "Mont Pourri",
        "slug": "mont-pourri",
        "lat": 45.5172,
        "lng": 6.8928,
        "altitude": 3779,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890abd",
        "name": "Aiguille de la Grande Sassière",
        "slug": "aiguille-de-la-grande-sassiere",
        "lat": 45.5194,
        "lng": 7.0706,
        "altitude": 3747,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ac1",
        "name": "Pointe de la Galise",
        "slug": "pointe-de-la-galise",
        "lat": 45.5303,
        "lng": 7.0892,
        "altitude": 3344,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ac2",
        "name": "Aiguille du Tour",
        "slug": "aiguille-du-tour",
        "lat": 45.9928,
        "lng": 7.0136,
        "altitude": 3542,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ac0",
        "name": "Grand Arc",
        "slug": "grand-arc",
        "lat": 45.5267,
        "lng": 6.6486,
        "altitude": 2477,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890abf",
        "name": "Pointe de l'Observatoire",
        "slug": "pointe-de-lobservatoire",
        "lat": 45.4533,
        "lng": 6.9228,
        "altitude": 3015,
    },
    {
        "id": "dce6fffe-591e-5c14-80e2-1d3927fde489",
        "name": "Pic du Midi de Bigorre",
        "slug": "pic-du-midi-de-bigorre",
        "lat": 42.9368,
        "lng": 0.1412,
        "altitude": 2877,
    },
    # Alpes — moyens massifs (mer de nuage idéale : 1400-3000m)
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890aca",
        "name": "Grand Pic de Belledonne",
        "slug": "grand-pic-de-belledonne",
        "lat": 45.2358,
        "lng": 5.8881,
        "altitude": 2927,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ac3",
        "name": "Pointe Percée",
        "slug": "pointe-percee",
        "lat": 46.0208,
        "lng": 6.5422,
        "altitude": 2750,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ac5",
        "name": "Grand Veymont",
        "slug": "grand-veymont",
        "lat": 44.9244,
        "lng": 5.5175,
        "altitude": 2341,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890acc",
        "name": "La Tournette",
        "slug": "la-tournette",
        "lat": 45.8303,
        "lng": 6.3017,
        "altitude": 2351,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890acd",
        "name": "Mont Charvin",
        "slug": "mont-charvin",
        "lat": 45.8039,
        "lng": 6.5108,
        "altitude": 2409,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890acb",
        "name": "Croix de Chamrousse",
        "slug": "croix-de-chamrousse",
        "lat": 45.1194,
        "lng": 5.8828,
        "altitude": 2250,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ac4",
        "name": "Dent d'Oche",
        "slug": "dent-doche",
        "lat": 46.3233,
        "lng": 6.7494,
        "altitude": 2222,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ac9",
        "name": "Mont Aiguille",
        "slug": "mont-aiguille",
        "lat": 44.7244,
        "lng": 5.6211,
        "altitude": 2087,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ac6",
        "name": "Chamechaude",
        "slug": "chamechaude",
        "lat": 45.2594,
        "lng": 5.7428,
        "altitude": 2082,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ac7",
        "name": "Dent de Crolles",
        "slug": "dent-de-crolles",
        "lat": 45.3528,
        "lng": 5.8736,
        "altitude": 2062,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ac8",
        "name": "Moucherotte",
        "slug": "moucherotte",
        "lat": 45.1208,
        "lng": 5.6511,
        "altitude": 1901,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ad1",
        "name": "Le Môle",
        "slug": "le-mole",
        "lat": 46.1167,
        "lng": 6.4333,
        "altitude": 1863,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ace",
        "name": "Parmelan",
        "slug": "parmelan",
        "lat": 45.9817,
        "lng": 6.2061,
        "altitude": 1832,
    },
    {
        "id": "38e5b59f-3596-5fb9-953d-095d00754ae6",
        "name": "Crêt de la Neige",
        "slug": "cret-de-la-neige",
        "lat": 46.3811,
        "lng": 5.6281,
        "altitude": 1720,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890acf",
        "name": "Semnoz",
        "slug": "semnoz",
        "lat": 45.8386,
        "lng": 6.1303,
        "altitude": 1699,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ad3",
        "name": "Revard",
        "slug": "revard",
        "lat": 45.65,
        "lng": 5.9833,
        "altitude": 1537,
    },
    {
        "id": "05ee50d6-47de-5c78-98f6-7a9f819f3e72",
        "name": "Grand Colombier",
        "slug": "grand-colombier",
        "lat": 45.9056,
        "lng": 5.6997,
        "altitude": 1531,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ad2",
        "name": "Col des Aravis",
        "slug": "col-des-aravis",
        "lat": 45.8581,
        "lng": 6.5036,
        "altitude": 1498,
    },
    {
        "id": "4b9e00e8-7b52-5c73-9b08-ff7e137f0349",
        "name": "Col de la Croix-Fry",
        "slug": "col-de-la-croix-fry",
        "lat": 45.9075,
        "lng": 6.5015,
        "altitude": 1477,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ad0",
        "name": "Mont Salève",
        "slug": "mont-saleve",
        "lat": 46.1339,
        "lng": 6.1633,
        "altitude": 1379,
    },
    # Vosges
    {
        "id": "175ea4e7-c1d4-5e5c-ba48-6a65eebf1ef2",
        "name": "Grand Ballon",
        "slug": "grand-ballon",
        "lat": 47.9004,
        "lng": 7.1005,
        "altitude": 1424,
    },
    {
        "id": "59b525e7-8e19-5a93-92da-4dd642e2d62d",
        "name": "Hohneck",
        "slug": "hohneck",
        "lat": 47.9986,
        "lng": 6.9758,
        "altitude": 1363,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ad5",
        "name": "Gazon du Faing",
        "slug": "gazon-du-faing",
        "lat": 48.0497,
        "lng": 7.0347,
        "altitude": 1303,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ad4",
        "name": "Petit Ballon",
        "slug": "petit-ballon",
        "lat": 47.9711,
        "lng": 7.0706,
        "altitude": 1272,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ad8",
        "name": "Brézouard",
        "slug": "brezouard",
        "lat": 48.2175,
        "lng": 7.1264,
        "altitude": 1228,
    },
    {
        "id": "267a3d35-4f37-51c0-8465-2d0a091911bb",
        "name": "Ballon d'Alsace",
        "slug": "ballon-d-alsace",
        "lat": 47.8193,
        "lng": 6.8576,
        "altitude": 1247,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ad6",
        "name": "Ballon de Servance",
        "slug": "ballon-de-servance",
        "lat": 47.8253,
        "lng": 6.7511,
        "altitude": 1216,
    },
    {
        "id": "2fc398c9-6b96-5a43-b521-04a4093a5c92",
        "name": "Champ du Feu",
        "slug": "champ-du-feu",
        "lat": 48.4,
        "lng": 7.2242,
        "altitude": 1099,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ad7",
        "name": "Donon",
        "slug": "donon",
        "lat": 48.5111,
        "lng": 7.1458,
        "altitude": 1009,
    },
    # Massif Central
    {
        "id": "fd8f1573-a4dc-5c65-96b7-5c5c59737df4",
        "name": "Puy de Sancy",
        "slug": "puy-de-sancy",
        "lat": 45.5264,
        "lng": 2.8086,
        "altitude": 1885,
    },
    {
        "id": "0183e8a1-1544-5089-89bf-4d804d890689",
        "name": "Plomb du Cantal",
        "slug": "plomb-du-cantal",
        "lat": 45.0489,
        "lng": 2.7561,
        "altitude": 1855,
    },
    {
        "id": "e03f09d7-b46e-51c3-9a03-9f64cad5c8db",
        "name": "Puy Mary",
        "slug": "puy-mary",
        "lat": 45.1128,
        "lng": 2.6736,
        "altitude": 1787,
    },
    {
        "id": "6e0496b7-ac97-5df5-a863-9b3eadc1329b",
        "name": "Mont Mézenc",
        "slug": "mont-mezenc",
        "lat": 44.9025,
        "lng": 4.1958,
        "altitude": 1753,
    },
    {
        "id": "3b4b1ce1-17b1-5409-b8a2-ca6ee5349a56",
        "name": "Pierre-sur-Haute",
        "slug": "pierre-sur-haute",
        "lat": 45.5317,
        "lng": 3.8972,
        "altitude": 1634,
    },
    {
        "id": "502b6550-2891-5100-a953-042046972a70",
        "name": "Mont Aigoual",
        "slug": "mont-aigoual",
        "lat": 44.1211,
        "lng": 3.5831,
        "altitude": 1567,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ad9",
        "name": "Mont Gerbier-de-Jonc",
        "slug": "mont-gerbier-de-jonc",
        "lat": 44.8419,
        "lng": 4.2203,
        "altitude": 1551,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890adb",
        "name": "Signal du Luguet",
        "slug": "signal-du-luguet",
        "lat": 45.3458,
        "lng": 3.2483,
        "altitude": 1551,
    },
    {
        "id": "42cd96c1-c2c0-5cd0-8534-3931e696790b",
        "name": "Puy de Dôme",
        "slug": "puy-de-dome",
        "lat": 45.7725,
        "lng": 2.9656,
        "altitude": 1465,
    },
    {
        "id": "e4c1a2b3-d4e5-5f67-8901-234567890ada",
        "name": "Crêt de l'Œillon",
        "slug": "cret-de-loeillon",
        "lat": 45.3844,
        "lng": 4.4892,
        "altitude": 1370,
    },
    # Provence & autres
    {
        "id": "0728f7c7-a0c9-5fb0-b87d-d9edc8696840",
        "name": "Mont Ventoux",
        "slug": "mont-ventoux",
        "lat": 44.1742,
        "lng": 5.2789,
        "altitude": 1912,
    },
    {
        "id": "9d408247-27d2-5937-8d7f-d82f4e4b93f5",
        "name": "Pic Saint-Loup",
        "slug": "pic-saint-loup",
        "lat": 43.7917,
        "lng": 3.7333,
        "altitude": 658,
    },
    {
        "id": "b3d23c82-d09d-5b4f-91f3-da789e135475",
        "name": "Roc'h Trévezel",
        "slug": "roch-trevezel",
        "lat": 48.3711,
        "lng": -3.9617,
        "altitude": 384,
    },
]


async def seed() -> None:
    async with async_session_maker() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM peaks"))
        count = result.scalar()
        if count and count > 0:
            logger.warning("seed_skipped", extra={"reason": "table peaks non vide", "count": count})
            print(f"⚠️  Table peaks contient déjà {count} entrée(s) — seed ignoré.")
            print("   Pour forcer : DELETE FROM peaks; puis relancer.")
            return

        for data in PEAKS:
            peak = Peak(**data)
            session.add(peak)

        await session.commit()
        print(f"✅ {len(PEAKS)} sommets insérés.")
        logger.info("seed_completed", extra={"count": len(PEAKS)})


async def main() -> None:
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
