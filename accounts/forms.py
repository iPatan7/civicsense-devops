from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from complaints.models import Ward

from .models import Profile

BOOTSTRAP = {"class": "form-control"}


class CitizenSignupForm(UserCreationForm):
    """Registration form for a citizen; the profile is filled in afterwards."""
    full_name = forms.CharField(max_length=80, widget=forms.TextInput(attrs=BOOTSTRAP))
    email = forms.EmailField(widget=forms.EmailInput(attrs=BOOTSTRAP))
    phone = forms.CharField(max_length=15, required=False,
                            widget=forms.TextInput(attrs=BOOTSTRAP))
    ward = forms.ModelChoiceField(queryset=Ward.objects.all(), required=False,
                                  widget=forms.Select(attrs={"class": "form-select"}))

    class Meta:
        model = User
        fields = ("username", "full_name", "email", "phone", "ward")
        widgets = {"username": forms.TextInput(attrs=BOOTSTRAP)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("password1", "password2"):
            self.fields[name].widget.attrs.update(BOOTSTRAP)

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        name_parts = self.cleaned_data["full_name"].split(" ", 1)
        user.first_name = name_parts[0]
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        user.email = self.cleaned_data["email"]
        user.save()
        Profile.objects.update_or_create(
            user=user,
            defaults={"phone": self.cleaned_data.get("phone", ""),
                      "ward": self.cleaned_data.get("ward")},
        )
        return user


class StyledLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(BOOTSTRAP)


class ProfileForm(forms.ModelForm):
    full_name = forms.CharField(max_length=80, widget=forms.TextInput(attrs=BOOTSTRAP))
    email = forms.EmailField(widget=forms.EmailInput(attrs=BOOTSTRAP))

    class Meta:
        model = Profile
        fields = ("phone", "address", "ward")
        widgets = {
            "phone": forms.TextInput(attrs=BOOTSTRAP),
            "address": forms.TextInput(attrs=BOOTSTRAP),
            "ward": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.instance.user
        self.fields["full_name"].initial = user.get_full_name()
        self.fields["email"].initial = user.email

    def save(self, commit=True):
        profile = super().save(commit)
        user = profile.user
        parts = self.cleaned_data["full_name"].split(" ", 1)
        user.first_name, user.last_name = parts[0], (parts[1] if len(parts) > 1 else "")
        user.email = self.cleaned_data["email"]
        user.save()
        return profile
