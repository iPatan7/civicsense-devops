"""Forms of the citizen portal and the authority dashboard."""
from django import forms

from .models import Category, Complaint, Feedback, Status, Ward

CONTROL = {"class": "form-control"}
SELECT = {"class": "form-select"}


class ComplaintForm(forms.ModelForm):
    """What a citizen fills in.  Category is optional on purpose - leaving it
    empty is the normal case and lets the NLP engine decide."""

    class Meta:
        model = Complaint
        fields = ("title", "description", "category", "ward", "address",
                  "landmark", "latitude", "longitude")
        widgets = {
            "title": forms.TextInput(attrs=dict(
                CONTROL, placeholder="Short summary, e.g. Street light not working near park",
                maxlength=150)),
            "description": forms.Textarea(attrs=dict(
                CONTROL, rows=6, id="id_description",
                placeholder="Describe the problem: what is wrong, since when, "
                            "and how it is affecting people.")),
            "category": forms.Select(attrs=SELECT),
            "ward": forms.Select(attrs=SELECT),
            "address": forms.TextInput(attrs=dict(CONTROL, placeholder="Street / area")),
            "landmark": forms.TextInput(attrs=dict(CONTROL, placeholder="Nearby landmark")),
            "latitude": forms.NumberInput(attrs=dict(CONTROL, step="any", id="id_latitude")),
            "longitude": forms.NumberInput(attrs=dict(CONTROL, step="any", id="id_longitude")),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        self.fields["category"].required = False
        self.fields["category"].empty_label = "Let the system decide (recommended)"
        self.fields["ward"].queryset = Ward.objects.all()
        self.fields["ward"].required = False
        self.fields["ward"].empty_label = "Select your ward"
        self.fields["latitude"].required = False
        self.fields["longitude"].required = False

    def clean_description(self):
        description = self.cleaned_data["description"].strip()
        if len(description) < 20:
            raise forms.ValidationError(
                "Please describe the problem in at least 20 characters so that "
                "it can be routed to the right department.")
        return description


class SupportForm(forms.Form):
    comment = forms.CharField(
        max_length=200, required=False,
        widget=forms.TextInput(attrs=dict(CONTROL, placeholder="Optional: add a detail")))


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ("rating", "comment")
        widgets = {
            "rating": forms.Select(
                choices=[(i, "%d star%s" % (i, "" if i == 1 else "s")) for i in range(1, 6)],
                attrs=SELECT),
            "comment": forms.Textarea(attrs=dict(CONTROL, rows=3,
                                                 placeholder="How was the service?")),
        }


class StatusUpdateForm(forms.Form):
    """Used by the authority dashboard to move a complaint forward."""
    status = forms.ChoiceField(
        choices=[(s.value, s.label) for s in Status if s != Status.DUPLICATE],
        widget=forms.Select(attrs=SELECT))
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs=dict(CONTROL, rows=2,
                                         placeholder="Action taken / remarks")))


class TrackForm(forms.Form):
    tracking_id = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs=dict(CONTROL, placeholder="CIV-2026-XXXXXX")))

    def clean_tracking_id(self):
        return self.cleaned_data["tracking_id"].strip().upper()
