"""
Fill an empty database with a realistic municipality so the platform can be
demonstrated immediately:

    python manage.py seed_demo            # ~120 complaints over the last 45 days
    python manage.py seed_demo --reset    # wipe the demo data first

The generated set deliberately contains duplicate reports of the same pothole,
the same overflowing drain and the same dead street light, so the duplicate
detection and the corroboration part of the priority score can be seen working.
"""
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Profile, Role
from complaints import services
from complaints.models import (Category, Complaint, Department, Feedback,
                               Status, TrainingSample, Ward)

DEPARTMENTS = [
    ("Public Works Department", "PWD", "pwd@city.gov.in", "Er. R. Sharma"),
    ("Water Supply and Sewerage Board", "WSSB", "water@city.gov.in", "Er. M. Kaur"),
    ("Sanitation and Solid Waste", "SWM", "sanitation@city.gov.in", "Mrs. A. Devi"),
    ("Electricity and Street Lighting", "ESL", "power@city.gov.in", "Er. S. Iyer"),
    ("Health and Veterinary Services", "HVS", "health@city.gov.in", "Dr. P. Nair"),
    ("Town Planning and Enforcement", "TPE", "planning@city.gov.in", "Sh. V. Rao"),
]

# code, name, department, severity, sla hours, icon
CATEGORIES = [
    ("ROADS", "Roads and Potholes", "PWD", 0.65, 72, "bi-cone-striped"),
    ("WATER", "Water Supply", "WSSB", 0.80, 24, "bi-droplet-half"),
    ("SEWER", "Sewerage and Drainage", "WSSB", 0.85, 24, "bi-water"),
    ("GARBAGE", "Garbage and Sanitation", "SWM", 0.60, 48, "bi-trash3"),
    ("LIGHT", "Street Lighting", "ESL", 0.45, 72, "bi-lightbulb"),
    ("ELECTRIC", "Electricity Supply", "ESL", 0.75, 12, "bi-lightning-charge"),
    ("ANIMAL", "Stray Animals", "HVS", 0.55, 48, "bi-bug"),
    ("ENCROACH", "Encroachment and Illegal Construction", "TPE", 0.40, 120, "bi-sign-stop"),
    ("PARKS", "Parks and Public Property", "PWD", 0.35, 120, "bi-tree"),
    ("POLLUTION", "Noise and Air Pollution", "HVS", 0.50, 72, "bi-cloud-haze2"),
]

WARDS = [
    ("W01", "Sector 17 Market", "Central", 30.7410, 76.7822),
    ("W02", "Sector 22 Residential", "Central", 30.7333, 76.7794),
    ("W03", "Industrial Area Phase 1", "East", 30.7060, 76.8020),
    ("W04", "Manimajra", "North", 30.7290, 76.8360),
    ("W05", "Dhanas Village", "West", 30.7620, 76.7480),
    ("W06", "Sector 43 Bus Terminal", "South", 30.7150, 76.7620),
]

# (title, description, ward index, category hint)
COMPLAINT_TEMPLATES = [
    ("Big pothole near the bus stop",
     "There is a very big pothole on the main road right in front of the bus stop. "
     "Two wheeler riders are falling every day and yesterday a scooter rider was injured. "
     "It has become worse after the rain.", 1),
    ("Pothole on the main road is dangerous",
     "A deep pothole has formed on the main road near the bus stop. Bikes are "
     "slipping into it and at night it is not visible at all because there is water in it.", 1),
    ("Road broken in front of the bus stand",
     "The road near the bus stand is completely broken with a large pothole. "
     "Please repair it, an accident can happen any time.", 1),
    ("No water supply since three days",
     "Our whole street has not received any water supply since the last three days. "
     "We are buying water from tankers and the elderly people are suffering a lot.", 2),
    ("Water is not coming in the taps",
     "There is no water supply in our lane since three days. Nobody from the department "
     "is responding to the phone. Please arrange a tanker urgently.", 2),
    ("Drain is overflowing on the road",
     "The drain behind the market is completely blocked and sewage is overflowing on "
     "the road. The smell is unbearable and mosquitoes are breeding there.", 0),
    ("Sewage water entering our houses",
     "Because the drain is choked, dirty sewage water is entering the ground floor of "
     "our houses. My child has fallen sick. This has been going on for two weeks.", 0),
    ("Street light not working",
     "The street light in front of house number 240 has not been working for one month. "
     "The whole lane is dark at night and women are afraid to walk.", 3),
    ("Lane is completely dark at night",
     "All three street lights of our lane are fused. It is completely dark and there "
     "have been two chain snatching incidents.", 3),
    ("Garbage not collected for a week",
     "The garbage vehicle has not come to our street for one week. The dustbin is "
     "overflowing and stray dogs are spreading the waste on the road.", 4),
    ("Dustbin overflowing near the school",
     "The community dustbin near the school gate is overflowing since many days. "
     "Children have to walk through the garbage. Please arrange the cleaning.", 4),
    ("Live wire hanging over the road",
     "An electric wire has come loose from the pole and is hanging very low over the "
     "road. It is a live wire and a serious danger for the school children who pass here.", 5),
    ("Transformer is sparking",
     "The transformer near our block is sparking loudly and there is a burning smell. "
     "Power also goes off frequently. This is an emergency, please send a team.", 5),
    ("Stray dogs are biting children",
     "A pack of stray dogs sits near the park gate and has bitten three children in "
     "the last week. Please catch them, we are afraid to send our children out.", 3),
    ("Cattle sitting on the main road",
     "Stray cattle are sitting in the middle of the main road near the crossing and "
     "the traffic gets blocked. It is dangerous at night.", 1),
    ("Shopkeepers have encroached the footpath",
     "The shopkeepers of the market have put their goods on the entire footpath. "
     "There is no space left to walk and people have to walk on the road.", 0),
    ("Illegal construction going on",
     "A building is being constructed with two extra floors than the sanctioned plan "
     "in our street. The material is also dumped on the public road.", 2),
    ("Park swings are broken",
     "The swings and the slide in the children park are broken and rusted. My son got "
     "a cut on his hand yesterday. Please repair them.", 4),
    ("Grass in the public garden not cut",
     "The grass in the public garden has not been cut for over two months and it has "
     "become a place for snakes and mosquitoes.", 5),
    ("Loud music till late night",
     "There is very loud DJ music from the marriage hall till two in the night every "
     "weekend. Patients and students are disturbed and nobody is listening.", 0),
    ("Factory smoke in residential area",
     "A small factory is releasing black smoke in our residential area. Children and "
     "elderly people are having breathing problems.", 2),
    ("Manhole cover is missing",
     "The manhole cover on the footpath near the temple is missing since last week. "
     "It is an open manhole and a child can fall inside. Very dangerous.", 3),
    ("Water pipeline burst on the road",
     "The main water pipeline has burst near the crossing and clean drinking water is "
     "being wasted on the road since morning.", 4),
    ("Speed breaker too high",
     "The new speed breaker near the school is too high and vehicles are getting "
     "damaged. Two wheelers lose balance on it.", 5),
    ("Dead animal on the roadside",
     "A dead dog has been lying on the roadside for two days. The smell is very bad "
     "and it is a health hazard for the whole street.", 1),
]

RESOLUTION_NOTES = [
    "Site inspected by the junior engineer and the work order was issued.",
    "Repair completed by the department crew and verified on site.",
    "Material arranged and the work was completed the same day.",
    "Cleaning done by the sanitation team, the area has been disinfected.",
    "Temporary fix done, permanent repair scheduled in the next work order.",
]


class Command(BaseCommand):
    help = "Create demo departments, wards, categories, users and complaints."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="delete the existing complaints and users first")
        parser.add_argument("--complaints", type=int, default=120,
                            help="how many complaints to generate (default 120)")

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(20260908)          # reproducible demo data

        if options["reset"]:
            Complaint.objects.all().delete()
            TrainingSample.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()
            self.stdout.write(self.style.WARNING("Existing demo data removed."))

        departments = self._create_departments()
        wards = self._create_wards()
        categories = self._create_categories(departments)
        citizens, staff = self._create_users(departments, wards)

        self._create_complaints(citizens, wards, options["complaints"])
        self._advance_workflow(staff)

        self.stdout.write(self.style.SUCCESS(
            "Seeded %d departments, %d wards, %d categories, %d users and %d complaints."
            % (len(departments), len(wards), len(categories),
               User.objects.count(), Complaint.objects.count())))
        self.stdout.write("Log in as  admin/admin123 (administrator), "
                          "officer/civic123 (ward officer), "
                          "staff_roads/civic123 (department staff), "
                          "citizen1/civic123 (citizen).")

    # -- reference data ----------------------------------------------------
    def _create_departments(self):
        departments = {}
        for name, code, email, head in DEPARTMENTS:
            department, _ = Department.objects.update_or_create(
                code=code, defaults={"name": name, "email": email, "head_name": head})
            departments[code] = department
        return departments

    def _create_wards(self):
        wards = []
        for code, name, zone, latitude, longitude in WARDS:
            ward, _ = Ward.objects.update_or_create(
                code=code,
                defaults={"name": name, "zone": zone, "latitude": latitude,
                          "longitude": longitude,
                          "population": random.randint(8000, 45000),
                          "councillor": "Councillor %s" % code})
            wards.append(ward)
        return wards

    def _create_categories(self, departments):
        categories = []
        for code, name, department_code, severity, sla, icon in CATEGORIES:
            category, _ = Category.objects.update_or_create(
                code=code,
                defaults={"name": name, "department": departments[department_code],
                          "severity": severity, "sla_hours": sla, "icon": icon})
            categories.append(category)
        return categories

    def _create_users(self, departments, wards):
        admin, created = User.objects.get_or_create(
            username="admin", defaults={"email": "admin@city.gov.in",
                                        "is_staff": True, "is_superuser": True})
        if created:
            admin.set_password("admin123")
            admin.save()
        Profile.objects.update_or_create(user=admin, defaults={"role": Role.ADMIN})

        officer = self._user("officer", "Ward Officer", Role.OFFICER,
                             department=departments["PWD"], ward=wards[0])
        staff = [officer]
        for code, username in (("PWD", "staff_roads"), ("WSSB", "staff_water"),
                               ("SWM", "staff_waste"), ("ESL", "staff_power"),
                               ("HVS", "staff_health"), ("TPE", "staff_planning")):
            staff.append(self._user(username, username.replace("_", " ").title(),
                                    Role.STAFF, department=departments[code]))

        citizens = [self._user("citizen%d" % index, "Citizen %d" % index, Role.CITIZEN,
                               ward=random.choice(wards))
                    for index in range(1, 13)]
        return citizens, staff

    def _user(self, username, full_name, role, department=None, ward=None):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": "%s@example.com" % username,
                      "first_name": full_name.split()[0],
                      "last_name": " ".join(full_name.split()[1:])})
        if created:
            user.set_password("civic123")
            user.save()
        Profile.objects.update_or_create(
            user=user,
            defaults={"role": role, "department": department, "ward": ward,
                      "phone": "9%09d" % random.randint(0, 999999999),
                      "is_verified": True})
        return user

    # -- complaints --------------------------------------------------------
    def _create_complaints(self, citizens, wards, how_many):
        now = timezone.now()
        created = 0
        while created < how_many:
            title, description, ward_index = random.choice(COMPLAINT_TEMPLATES)
            # About a third of the reports stay in the ward the template
            # belongs to - those are the ones that become duplicates of each
            # other.  The rest are spread over the city, where the same
            # sentence describes a different pothole in a different street.
            if random.random() < 0.35:
                ward = wards[ward_index % len(wards)]
                jitter = 0.0009               # ~100 m: inside the merge radius
            else:
                ward = random.choice(wards)
                jitter = 0.02                 # ~2 km: a different problem
            citizen = random.choice(citizens)
            # most complaints are recent, with a tail of older ones that have
            # already breached their SLA
            age_hours = (random.randint(1, 14 * 24) if random.random() < 0.7
                         else random.randint(14 * 24, 45 * 24))
            data = {
                "title": title,
                "description": description,
                "ward": ward,
                "address": "%s, %s" % (random.choice(
                    ["Main Road", "Street 4", "Near Community Centre", "Market Lane",
                     "Housing Board Colony", "School Road"]), ward.name),
                "landmark": random.choice(["bus stop", "temple", "school gate",
                                           "water tank", "park", "petrol pump"]),
                "latitude": round(float(ward.latitude) + random.uniform(-jitter, jitter), 6),
                "longitude": round(float(ward.longitude) + random.uniform(-jitter, jitter), 6),
                "category": None,
            }
            complaint, _ = services.file_complaint(
                citizen, data, source=random.choice(["WEB", "MOBILE", "PHONE"]))

            # Back-date the complaint and move the SLA clock with it, so that
            # some of the older complaints are genuinely overdue.
            sla_hours = complaint.sla_hours
            complaint.created_at = now - timedelta(hours=age_hours)
            complaint.set_due_date(sla_hours)
            complaint.save(update_fields=["created_at", "due_at"])
            complaint.updates.update(created_at=complaint.created_at)
            created += 1

    def _advance_workflow(self, staff):
        """Move a realistic share of the complaints through the workflow."""
        open_complaints = list(Complaint.objects.exclude(status=Status.DUPLICATE))
        random.shuffle(open_complaints)

        for index, complaint in enumerate(open_complaints):
            chance = random.random()
            crew = random.choice(staff)

            if chance < 0.45:                       # resolved and closed
                services.assign(complaint, crew, actor=staff[0])
                services.change_status(complaint, Status.IN_PROGRESS, actor=crew,
                                       note="Crew sent to the site.")
                services.change_status(complaint, Status.RESOLVED, actor=crew,
                                       note=random.choice(RESOLUTION_NOTES))
                resolved_at = complaint.created_at + timedelta(
                    hours=random.uniform(2, complaint.sla_hours * 1.4))
                Complaint.objects.filter(pk=complaint.pk).update(resolved_at=resolved_at)
                if random.random() < 0.6:
                    complaint.refresh_from_db()
                    Feedback.objects.update_or_create(
                        complaint=complaint,
                        defaults={"rating": random.choice([5, 4, 4, 3, 5, 2]),
                                  "comment": random.choice(
                                      ["Work was done properly, thank you.",
                                       "Resolved but it took too long.",
                                       "Good and quick response.",
                                       "Problem came back after a few days.", ""])})
            elif chance < 0.62:                     # work in progress
                services.assign(complaint, crew, actor=staff[0])
                services.change_status(complaint, Status.IN_PROGRESS, actor=crew,
                                       note="Material arranged, work started.")
            elif chance < 0.75:                     # assigned, not started
                services.assign(complaint, crew, actor=staff[0])

            # every twelfth complaint is reviewed by an officer: usually the
            # predicted category is confirmed, sometimes it is corrected, and
            # both cases become training data for the classifier
            if index % 12 == 0 and complaint.category:
                if random.random() < 0.25:
                    wrong = Category.objects.exclude(pk=complaint.category_id).order_by("?").first()
                    services.correct_category(complaint, wrong, actor=staff[0])
                else:
                    services.correct_category(complaint, complaint.category, actor=staff[0])

            # a few citizens support somebody else's complaint
            if index % 7 == 0:
                supporters = User.objects.filter(profile__role=Role.CITIZEN).exclude(
                    pk=complaint.citizen_id).order_by("?")[:random.randint(1, 3)]
                for supporter in supporters:
                    services.add_support(complaint, supporter, "Same problem in our street.")
