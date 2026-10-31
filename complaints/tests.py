"""
Tests for the Civic Complaint Intelligence Platform.

Three groups:
  1. the NLP engine on its own (no database),
  2. the service layer - categorisation, duplicates, priority, workflow,
  3. the web layer - access control and the pages a user actually opens.

Run with:  python manage.py test
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, Role
from nlpengine import (analyse_sentiment, analyse_urgency, band_for, classify,
                       find_similar, haversine_metres, score_complaint)
from nlpengine.preprocess import stem, tokenize
from nlpengine.similarity import cosine_similarity

from . import services
from .models import (Category, Complaint, Department, Feedback, Status,
                     Support, TrainingSample, Ward)


# --------------------------------------------------------------------------
# 1. The NLP engine
# --------------------------------------------------------------------------
class PreprocessTests(TestCase):
    def test_stopwords_and_stemming(self):
        tokens = tokenize("The street lights on MG Road are NOT working")
        self.assertIn("light", tokens)
        self.assertIn("not", tokens)          # negation must survive
        self.assertNotIn("the", tokens)
        self.assertNotIn("are", tokens)

    def test_stem_keeps_words_readable(self):
        self.assertEqual(stem("lights"), stem("lighting"))
        self.assertEqual(stem("water"), "water")
        self.assertEqual(stem("dogs"), "dog")


class ClassifierTests(TestCase):
    def test_each_service_is_recognised(self):
        expectations = {
            "There is a huge pothole on the main road near the bus stop": "ROADS",
            "No water supply in our colony since three days": "WATER",
            "Drain is blocked and sewage is overflowing on the street": "SEWER",
            "Garbage has not been collected for one week": "GARBAGE",
            "Street light in front of my house is not working": "LIGHT",
            "Transformer is sparking and the wire is hanging low": "ELECTRIC",
            "Stray dogs are biting children near the school": "ANIMAL",
            "Shopkeepers have encroached the whole footpath": "ENCROACH",
            "The swings in the children park are broken": "PARKS",
            "Loud music from the marriage hall till late night": "POLLUTION",
        }
        for text, expected in expectations.items():
            with self.subTest(text=text):
                self.assertEqual(classify(text)["category"], expected)

    def test_confidence_and_explanation(self):
        result = classify("Sewage is overflowing from the manhole on our street")
        self.assertGreater(result["confidence"], 0.5)
        self.assertTrue(result["keywords"])

    def test_a_correction_changes_the_model(self):
        text = "The community hall projector is not working"
        before = classify(text)["category"]
        after = classify(text, extra_samples=[(text, "PARKS")] * 5)["category"]
        self.assertEqual(after, "PARKS")
        self.assertNotEqual(after, before or "")


class SentimentAndPriorityTests(TestCase):
    def test_negation_is_handled(self):
        self.assertLess(analyse_sentiment("The road is not clean")["polarity"], 0)
        self.assertGreater(analyse_sentiment("The road was cleaned, thank you")["polarity"], 0)

    def test_emergency_words_raise_urgency(self):
        emergency = analyse_urgency("A live wire has fallen near the school children")
        routine = analyse_urgency("Please put one more bench in the park")
        self.assertGreater(emergency["urgency"], 0.8)
        self.assertEqual(routine["urgency"], 0.0)

    def test_priority_bands(self):
        self.assertEqual(band_for(90), "CRITICAL")
        self.assertEqual(band_for(60), "HIGH")
        self.assertEqual(band_for(40), "MEDIUM")
        self.assertEqual(band_for(10), "LOW")

    def test_emergency_is_never_low_priority(self):
        result = score_complaint("Live wire fallen on the road", category_severity=0.1)
        self.assertEqual(result["priority"], "CRITICAL")
        self.assertTrue(result["critical_patterns"])

    def test_supporters_and_ageing_push_the_score_up(self):
        text = "Garbage is not collected from our street since one week"
        alone = score_complaint(text, category_severity=0.6)["score"]
        crowd = score_complaint(text, category_severity=0.6, supporters=5,
                                sla_fraction_used=1.0)["score"]
        self.assertGreater(crowd, alone)


class SimilarityTests(TestCase):
    def setUp(self):
        self.candidates = [{
            "id": 1,
            "text": "There is a big pothole on MG road near the bus stop, bikes are falling",
            "latitude": 30.7333, "longitude": 76.7794, "ward": 1,
            "age_days": 2, "category": "ROADS",
        }]

    def test_same_problem_same_place_is_a_duplicate(self):
        matches = find_similar(
            "Deep pothole in front of the bus stop on MG road, scooters keep falling",
            self.candidates, latitude=30.7334, longitude=76.7795, ward=1,
            category="ROADS")
        self.assertTrue(matches[0]["is_duplicate"])
        self.assertLess(matches[0]["distance_m"], 300)

    def test_same_words_far_away_is_not_a_duplicate(self):
        matches = find_similar(
            "Deep pothole in front of the bus stop on MG road, scooters keep falling",
            self.candidates, latitude=28.6100, longitude=77.2000, ward=9,
            category="ROADS")
        self.assertFalse(matches[0]["is_duplicate"])

    def test_a_different_problem_is_not_similar(self):
        matches = find_similar("Loud music from the marriage hall till midnight",
                               self.candidates, latitude=30.7334, longitude=76.7795,
                               ward=1, category="POLLUTION")
        self.assertEqual(matches, [])

    def test_old_complaints_are_not_candidates(self):
        old = dict(self.candidates[0], age_days=90)
        self.assertEqual(find_similar("Big pothole on MG road near the bus stop",
                                      [old], ward=1), [])

    def test_cosine_and_distance(self):
        self.assertGreater(cosine_similarity("no water supply", "water supply is not coming"), 0)
        self.assertEqual(cosine_similarity("pothole on the road", "loud music at night"), 0)
        self.assertAlmostEqual(haversine_metres(30.7333, 76.7794, 30.7340, 76.7800),
                               97, delta=8)


# --------------------------------------------------------------------------
# 2. The service layer
# --------------------------------------------------------------------------
class CivicTestCase(TestCase):
    """Shared fixture: two departments, one ward, three categories, users."""

    def setUp(self):
        self.pwd = Department.objects.create(name="Public Works", code="PWD")
        self.swm = Department.objects.create(name="Sanitation", code="SWM")
        self.esl = Department.objects.create(name="Electricity", code="ESL")
        self.roads = Category.objects.create(name="Roads and Potholes", code="ROADS",
                                             department=self.pwd, severity=0.65,
                                             sla_hours=72)
        self.garbage = Category.objects.create(name="Garbage", code="GARBAGE",
                                               department=self.swm, severity=0.6,
                                               sla_hours=48)
        self.electric = Category.objects.create(name="Electricity", code="ELECTRIC",
                                                department=self.esl, severity=0.75,
                                                sla_hours=12)
        self.wssb = Department.objects.create(name="Water Board", code="WSSB")
        self.water = Category.objects.create(name="Water Supply", code="WATER",
                                             department=self.wssb, severity=0.8,
                                             sla_hours=24)
        self.ward = Ward.objects.create(name="Sector 22", code="W02",
                                        zone="Central", latitude=30.7333,
                                        longitude=76.7794)
        self.citizen = self._user("ramesh", Role.CITIZEN)
        self.other_citizen = self._user("sunita", Role.CITIZEN)
        self.officer = self._user("officer", Role.OFFICER, self.pwd)
        self.staff = self._user("crew", Role.STAFF, self.pwd)

    def _user(self, username, role, department=None):
        user = User.objects.create_user(username=username, password="civic123")
        Profile.objects.update_or_create(
            user=user, defaults={"role": role, "department": department})
        return user

    def _file(self, title, description, citizen=None, **extra):
        data = {"title": title, "description": description, "ward": self.ward,
                "address": "Main Road", "landmark": "bus stop",
                "latitude": 30.7333, "longitude": 76.7794, "category": None}
        data.update(extra)
        return services.file_complaint(citizen or self.citizen, data)


class FilingTests(CivicTestCase):
    def test_complaint_is_categorised_routed_and_scheduled(self):
        complaint, _ = self._file(
            "Huge pothole on the road",
            "A very big pothole has formed on the main road near the bus stop and "
            "two wheeler riders are falling into it every day.")
        self.assertEqual(complaint.category, self.roads)
        self.assertEqual(complaint.department, self.pwd)      # routing follows category
        self.assertTrue(complaint.tracking_id.startswith("CIV-"))
        self.assertIsNotNone(complaint.due_at)
        self.assertTrue(complaint.is_auto_categorised)
        self.assertGreater(complaint.ai_confidence, 0.3)
        self.assertTrue(complaint.priority_reasons)

    def test_an_emergency_gets_a_short_sla(self):
        complaint, _ = self._file(
            "Live wire on the road",
            "A live wire has fallen on the road near the school gate and children "
            "pass from here every morning. Very dangerous.")
        self.assertEqual(complaint.priority, "CRITICAL")
        self.assertLessEqual((complaint.due_at - complaint.created_at).total_seconds() / 3600, 12)

    def test_citizen_can_override_the_predicted_category(self):
        complaint, _ = self._file("Garbage problem",
                                  "The dustbin has not been emptied for many days now.",
                                  category=self.garbage)
        self.assertEqual(complaint.category, self.garbage)
        self.assertFalse(complaint.is_auto_categorised)

    def test_a_short_description_is_rejected_by_the_form(self):
        from .forms import ComplaintForm
        form = ComplaintForm({"title": "Problem", "description": "pothole"})
        self.assertFalse(form.is_valid())
        self.assertIn("description", form.errors)


class DuplicateTests(CivicTestCase):
    def test_second_report_of_the_same_problem_is_merged(self):
        first, _ = self._file(
            "Big pothole near the bus stop",
            "There is a very big pothole on the main road in front of the bus stop "
            "and two wheeler riders are falling every day.")
        second, matches = self._file(
            "Deep pothole in front of the bus stand",
            "A deep pothole on the main road near the bus stop, scooter riders keep "
            "falling into it and it is full of water.",
            citizen=self.other_citizen)

        second.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(second.status, Status.DUPLICATE)
        self.assertEqual(second.duplicate_of, first)
        self.assertEqual(first.support_count, 1)
        self.assertTrue(matches)

    def test_the_same_words_in_another_ward_are_not_merged(self):
        self._file("Big pothole near the bus stop",
                   "There is a very big pothole on the main road in front of the bus "
                   "stop and two wheeler riders are falling every day.")
        far_ward = Ward.objects.create(name="Manimajra", code="W04", zone="North",
                                       latitude=30.7290, longitude=76.8360)
        second, _ = self._file("Big pothole near the bus stop",
                               "There is a very big pothole on the main road in front "
                               "of the bus stop and two wheeler riders are falling.",
                               citizen=self.other_citizen, ward=far_ward,
                               latitude=30.7290, longitude=76.8360)
        second.refresh_from_db()
        self.assertNotEqual(second.status, Status.DUPLICATE)

    def test_an_officer_can_separate_a_wrong_merge(self):
        first, _ = self._file("Pothole near the bus stop",
                              "Big pothole on the main road near the bus stop, bikes "
                              "are falling into it every single day.")
        second, _ = self._file("Pothole at the bus stop",
                               "There is a big pothole on the main road at the bus "
                               "stop and bikes keep falling into it.",
                               citizen=self.other_citizen)
        second.refresh_from_db()
        self.assertEqual(second.status, Status.DUPLICATE)

        services.unmerge(second, actor=self.officer)
        second.refresh_from_db()
        first.refresh_from_db()
        self.assertIsNone(second.duplicate_of)
        self.assertEqual(first.support_count, 0)

    def test_duplicates_never_chain(self):
        first, _ = self._file("Pothole near the bus stop",
                              "Big pothole on the main road near the bus stop, bikes "
                              "are falling into it every single day.")
        second, _ = self._file("Pothole at the bus stop",
                               "There is a big pothole on the main road at the bus "
                               "stop and bikes keep falling into it.",
                               citizen=self.other_citizen)
        third, _ = self._file("Same pothole at the bus stop again",
                              "Big pothole on the main road at the bus stop, two "
                              "wheelers are falling into it.",
                              citizen=self._user("kavita", Role.CITIZEN))
        third.refresh_from_db()
        self.assertEqual(third.duplicate_of, first)     # not the second one


class PriorityAndWorkflowTests(CivicTestCase):
    def test_support_raises_the_priority(self):
        complaint, _ = self._file(
            "Garbage not collected",
            "The garbage of our street has not been picked up for one week and the "
            "dustbin is overflowing on the footpath.")
        before = complaint.priority_score
        services.add_support(complaint, self.other_citizen, "Same in my lane")
        complaint.refresh_from_db()
        self.assertEqual(complaint.support_count, 1)
        self.assertGreater(complaint.priority_score, before)

    def test_one_citizen_can_support_only_once(self):
        complaint, _ = self._file(
            "Garbage not collected",
            "The garbage of our street has not been picked up for one week and the "
            "dustbin is overflowing on the footpath.")
        services.add_support(complaint, self.other_citizen)
        services.add_support(complaint, self.other_citizen)
        self.assertEqual(Support.objects.filter(complaint=complaint).count(), 1)

    def test_status_flow_records_timestamps_and_audit_trail(self):
        complaint, _ = self._file(
            "Street light not working",
            "The street light in front of our house has not been working for a month "
            "and the lane is completely dark.")
        services.assign(complaint, self.staff, actor=self.officer)
        complaint.refresh_from_db()
        self.assertEqual(complaint.assigned_to, self.staff)
        self.assertEqual(complaint.status, Status.ASSIGNED)
        self.assertIsNotNone(complaint.acknowledged_at)

        services.change_status(complaint, Status.RESOLVED, actor=self.staff,
                               note="Bulb replaced")
        complaint.refresh_from_db()
        self.assertIsNotNone(complaint.resolved_at)
        self.assertIn("Bulb replaced", complaint.resolution_note)
        self.assertGreaterEqual(complaint.updates.count(), 3)

    def test_a_bad_rating_reopens_the_complaint(self):
        complaint, _ = self._file(
            "Street light not working",
            "The street light in front of our house has not been working for a month "
            "and the lane is completely dark.")
        services.change_status(complaint, Status.RESOLVED, actor=self.staff)
        services.record_feedback(complaint, rating=1, comment="Still not fixed")
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Status.IN_PROGRESS)
        self.assertEqual(Feedback.objects.get(complaint=complaint).rating, 1)

    def test_overdue_detection(self):
        complaint, _ = self._file(
            "Street light not working",
            "The street light in front of our house has not been working for a month "
            "and the lane is completely dark.")
        Complaint.objects.filter(pk=complaint.pk).update(
            due_at=timezone.now() - timedelta(hours=5))
        complaint.refresh_from_db()
        self.assertTrue(complaint.is_overdue)
        self.assertEqual(complaint.sla_state, "breached")
        self.assertEqual(services.dashboard_metrics()["overdue"], 1)

    def test_officer_correction_creates_a_training_sample(self):
        complaint, _ = self._file(
            "Wire hanging over the road",
            "An electric wire is hanging very low over the road in front of the "
            "school and it may touch a vehicle.")
        services.correct_category(complaint, self.garbage, actor=self.officer)
        complaint.refresh_from_db()
        self.assertEqual(complaint.category, self.garbage)
        self.assertEqual(complaint.department, self.swm)
        self.assertTrue(complaint.category_corrected)
        self.assertEqual(TrainingSample.objects.filter(
            category_code="GARBAGE").count(), 1)


# --------------------------------------------------------------------------
# 3. The web layer
# --------------------------------------------------------------------------
class PageTests(CivicTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.complaint, _ = self._file(
            "Pothole on the main road",
            "A big pothole has formed on the main road near the bus stop and two "
            "wheeler riders are falling into it.")

    def test_public_pages_open(self):
        for url in (reverse("complaints:home"), reverse("complaints:browse"),
                    reverse("complaints:track"),
                    reverse("complaints:detail", args=[self.complaint.tracking_id]),
                    "/healthz"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    @override_settings(CIVIC_RELEASE="3f2a91c0", CIVIC_SLOT="green")
    def test_health_endpoint_reports_the_release(self):
        # The deployment smoke test relies on this to see which build is live.
        self.assertEqual(self.client.get("/healthz").json(),
                         {"status": "ok", "release": "3f2a91c0", "slot": "green"})

    def test_filing_requires_login(self):
        response = self.client.get(reverse("complaints:file_complaint"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_citizen_can_file_from_the_web_form(self):
        self.client.login(username="ramesh", password="civic123")
        response = self.client.post(reverse("complaints:file_complaint"), {
            "title": "Drain is choked near the temple",
            "description": "The drain near the temple is completely choked and dirty "
                           "water is standing on the road since last week.",
            "ward": self.ward.pk, "address": "Temple Street", "landmark": "temple",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Complaint.objects.filter(citizen=self.citizen).count(), 2)

    def test_citizen_cannot_open_the_authority_dashboard(self):
        self.client.login(username="ramesh", password="civic123")
        self.assertEqual(self.client.get(reverse("dashboard:index")).status_code, 403)

    def test_officer_sees_the_dashboard_and_the_queue(self):
        self.client.login(username="officer", password="civic123")
        for url in (reverse("dashboard:index"), reverse("dashboard:queue"),
                    reverse("dashboard:duplicates"), reverse("dashboard:reports"),
                    reverse("dashboard:detail", args=[self.complaint.tracking_id])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_staff_only_sees_the_complaints_of_their_department(self):
        garbage_complaint, _ = self._file(
            "Garbage not lifted from our street",
            "The garbage of the whole street has not been lifted for one week and "
            "the dustbin is overflowing.")
        services.correct_category(garbage_complaint, self.garbage, actor=self.officer)

        self.client.login(username="crew", password="civic123")   # PWD staff
        response = self.client.get(reverse("dashboard:queue"))
        body = response.content.decode()
        self.assertIn(self.complaint.tracking_id, body)           # PWD complaint
        self.assertNotIn(garbage_complaint.tracking_id, body)     # SWM complaint

    def test_live_analysis_api(self):
        self.client.login(username="ramesh", password="civic123")
        response = self.client.post(
            reverse("complaints:api_analyse"),
            data={"title": "No water supply",
                  "description": "There has been no water supply in our colony for "
                                 "the last three days and tankers are not coming.",
                  "ward": self.ward.pk},
            content_type="application/json")
        payload = response.json()
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["category"]["code"], "WATER")
        self.assertIn(payload["priority"]["label"],
                      ["LOW", "MEDIUM", "HIGH", "CRITICAL"])

    def test_supporting_a_complaint_from_the_page(self):
        self.client.login(username="sunita", password="civic123")
        response = self.client.post(
            reverse("complaints:support", args=[self.complaint.tracking_id]),
            {"comment": "Same problem here"})
        self.assertEqual(response.status_code, 302)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.support_count, 1)

    def test_officer_updates_a_status_from_the_dashboard(self):
        self.client.login(username="officer", password="civic123")
        self.client.post(
            reverse("dashboard:update_status", args=[self.complaint.tracking_id]),
            {"status": Status.IN_PROGRESS, "note": "Crew sent to the site"})
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.IN_PROGRESS)

    def test_registration_creates_a_citizen_profile(self):
        response = self.client.post(reverse("accounts:signup"), {
            "username": "newuser", "full_name": "New User",
            "email": "new@example.com", "phone": "9876543210",
            "password1": "CivicPass!234", "password2": "CivicPass!234"})
        self.assertEqual(response.status_code, 302)
        profile = Profile.objects.get(user__username="newuser")
        self.assertEqual(profile.role, Role.CITIZEN)
