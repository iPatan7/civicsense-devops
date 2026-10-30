from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render

from .forms import CitizenSignupForm, ProfileForm, StyledLoginForm


class CivicLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = StyledLoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        profile = getattr(self.request.user, "profile", None)
        if profile and profile.is_authority:
            return "/authority/"
        return super().get_success_url()


class CivicLogoutView(LogoutView):
    http_method_names = ["get", "post", "options"]

    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)


def signup(request):
    if request.user.is_authenticated:
        return redirect("complaints:my_complaints")
    form = CitizenSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome! Your citizen account is ready.")
        return redirect("complaints:file_complaint")
    return render(request, "accounts/signup.html", {"form": form})


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user.profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})
