import unicodedata

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db import transaction

from .imagenes import actualizar_foto_perfil, validar_foto_perfil


User = get_user_model()


class RecuperarPasswordForm(PasswordResetForm):
    email = forms.EmailField(
        label="Correo electrónico",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "auth-input auth-input-simple",
                "autocomplete": "email",
                "placeholder": "nombre@empresa.com",
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"]

        if not any(self.get_users(email)):
            raise ValidationError(
                "No encontramos una cuenta activa asociada a este correo."
            )

        return email

    def get_users(self, email):
        """
        Permite que una cuenta creada con Google establezca una contraseña
        local de respaldo después de verificar su correo.
        """
        email_field_name = User.get_email_field_name()
        active_users = User._default_manager.filter(
            **{
                f"{email_field_name}__iexact": email,
                "is_active": True,
            }
        )

        normalized_email = unicodedata.normalize("NFKC", email).casefold()

        return (
            user
            for user in active_users
            if unicodedata.normalize(
                "NFKC",
                getattr(user, email_field_name),
            ).casefold()
            == normalized_email
        )


class CambiarPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="Nueva contraseña",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "auth-input auth-input-simple",
                "autocomplete": "new-password",
                "placeholder": "Nueva contraseña",
            }
        ),
    )
    new_password2 = forms.CharField(
        label="Confirmar contraseña",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "auth-input auth-input-simple",
                "autocomplete": "new-password",
                "placeholder": "Repite la contraseña",
            }
        ),
    )


class PerfilUsuarioForm(forms.Form):
    foto = forms.ImageField(
        label="Foto de perfil",
        required=False,
        validators=[validar_foto_perfil],
        widget=forms.FileInput(
            attrs={
                "class": "profile-photo-input",
                "accept": "image/jpeg,image/png,image/webp",
                "data-photo-input": "",
            }
        ),
    )
    eliminar_foto = forms.BooleanField(
        label="Quitar foto actual",
        required=False,
        widget=forms.CheckboxInput(
            attrs={
                "class": "profile-photo-remove-input",
                "data-photo-remove": "",
            }
        ),
    )
    first_name = forms.CharField(
        label="Nombre",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "profile-input",
                "autocomplete": "given-name",
                "placeholder": "Tu nombre",
            }
        ),
    )
    last_name = forms.CharField(
        label="Apellidos",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "profile-input",
                "autocomplete": "family-name",
                "placeholder": "Tus apellidos",
            }
        ),
    )
    email = forms.EmailField(
        label="Correo corporativo",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "profile-input",
                "autocomplete": "email",
                "placeholder": "nombre@empresa.com",
            }
        ),
    )
    numero_empleado = forms.CharField(
        label="Número de empleado",
        max_length=40,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "profile-input",
                "autocomplete": "off",
                "placeholder": "Ej. CRB-0248",
            }
        ),
    )
    telefono = forms.CharField(
        label="Teléfono",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "profile-input",
                "autocomplete": "tel",
                "inputmode": "tel",
                "placeholder": "+52 55 0000 0000",
            }
        ),
    )
    area = forms.CharField(
        label="Área o departamento",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "profile-input",
                "autocomplete": "organization-title",
                "placeholder": "Ej. Operaciones",
            }
        ),
    )
    cargo = forms.CharField(
        label="Cargo",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "profile-input",
                "autocomplete": "organization-title",
                "placeholder": "Ej. Analista de operaciones",
            }
        ),
    )

    def __init__(self, *args, user, perfil, **kwargs):
        self.user = user
        self.perfil = perfil
        is_bound = bool(args and args[0] is not None) or kwargs.get("data") is not None

        if not is_bound:
            kwargs["initial"] = {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "numero_empleado": perfil.numero_empleado,
                "telefono": perfil.telefono,
                "area": perfil.area,
                "cargo": perfil.cargo,
            }

        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        email_in_use = User.objects.exclude(pk=self.user.pk).filter(
            email__iexact=email
        ).exists()

        if email_in_use:
            raise forms.ValidationError(
                "Este correo ya está asociado a otra cuenta."
            )

        return email

    def clean_telefono(self):
        telefono = self.cleaned_data["telefono"].strip()
        digit_count = sum(character.isdigit() for character in telefono)

        if telefono and digit_count < 7:
            raise forms.ValidationError(
                "Escribe un teléfono válido con al menos 7 números."
            )

        return telefono

    @transaction.atomic
    def save(self):
        self.user.first_name = self.cleaned_data["first_name"].strip()
        self.user.last_name = self.cleaned_data["last_name"].strip()
        self.user.email = self.cleaned_data["email"]
        self.user.save(update_fields=["first_name", "last_name", "email"])

        self.perfil.numero_empleado = self.cleaned_data["numero_empleado"].strip()
        self.perfil.telefono = self.cleaned_data["telefono"]
        self.perfil.area = self.cleaned_data["area"].strip()
        self.perfil.cargo = self.cleaned_data["cargo"].strip()
        self.perfil.save(
            update_fields=[
                "numero_empleado",
                "telefono",
                "area",
                "cargo",
                "actualizado_at",
            ]
        )

        actualizar_foto_perfil(
            self.perfil,
            nueva_foto=self.cleaned_data.get("foto"),
            eliminar=self.cleaned_data.get("eliminar_foto", False),
        )

        return self.perfil


class AdministrarUsuarioForm(forms.Form):
    foto = forms.ImageField(
        label="Foto de perfil",
        required=False,
        validators=[validar_foto_perfil],
        widget=forms.FileInput(
            attrs={
                "class": "user-photo-input",
                "accept": "image/jpeg,image/png,image/webp",
                "data-photo-input": "",
            }
        ),
    )
    eliminar_foto = forms.BooleanField(
        label="Quitar foto actual",
        required=False,
        widget=forms.CheckboxInput(
            attrs={
                "class": "user-photo-remove-input",
                "data-photo-remove": "",
            }
        ),
    )
    username = forms.CharField(
        label="Usuario",
        max_length=150,
        validators=[UnicodeUsernameValidator()],
        widget=forms.TextInput(
            attrs={
                "class": "user-admin-input",
                "autocomplete": "username",
                "placeholder": "Ej. mfong",
            }
        ),
    )
    first_name = forms.CharField(
        label="Nombre",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "user-admin-input",
                "autocomplete": "given-name",
                "placeholder": "Nombre",
            }
        ),
    )
    last_name = forms.CharField(
        label="Apellidos",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "user-admin-input",
                "autocomplete": "family-name",
                "placeholder": "Apellidos",
            }
        ),
    )
    email = forms.EmailField(
        label="Correo corporativo",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "user-admin-input",
                "autocomplete": "email",
                "placeholder": "nombre@empresa.com",
            }
        ),
    )
    numero_empleado = forms.CharField(
        label="Número de empleado",
        max_length=40,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "user-admin-input",
                "placeholder": "Ej. CRB-0248",
            }
        ),
    )
    telefono = forms.CharField(
        label="Teléfono",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "user-admin-input",
                "autocomplete": "tel",
                "inputmode": "tel",
                "placeholder": "+52 55 0000 0000",
            }
        ),
    )
    area = forms.CharField(
        label="Área o departamento",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "user-admin-input",
                "placeholder": "Ej. Operaciones",
            }
        ),
    )
    cargo = forms.CharField(
        label="Cargo",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "user-admin-input",
                "placeholder": "Ej. Analista",
            }
        ),
    )
    rol = forms.ChoiceField(
        label="Rol del sistema",
        choices=(),
        widget=forms.Select(attrs={"class": "user-admin-select"}),
    )
    activo = forms.BooleanField(
        label="Cuenta activa",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "user-admin-checkbox"}),
    )
    password1 = forms.CharField(
        label="Contraseña",
        required=False,
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "user-admin-input",
                "autocomplete": "new-password",
                "placeholder": "Mínimo 8 caracteres",
            }
        ),
    )
    password2 = forms.CharField(
        label="Confirmar contraseña",
        required=False,
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "user-admin-input",
                "autocomplete": "new-password",
                "placeholder": "Repite la contraseña",
            }
        ),
    )

    def __init__(self, *args, actor, instance=None, **kwargs):
        self.actor = actor
        self.instance = instance
        self.is_edit = instance is not None
        super().__init__(*args, **kwargs)

        from .models import PerfilUsuario

        self.fields["rol"].choices = PerfilUsuario.Rol.choices

        if self.is_edit:
            perfil, _ = PerfilUsuario.objects.get_or_create(user=instance)
            self.fields["username"].disabled = True
            self.fields["password1"].label = "Nueva contraseña"
            self.fields["password1"].widget.attrs["placeholder"] = (
                "Déjala vacía para conservar la actual"
            )
            self.initial.update(
                {
                    "username": instance.username,
                    "first_name": instance.first_name,
                    "last_name": instance.last_name,
                    "email": instance.email,
                    "numero_empleado": perfil.numero_empleado,
                    "telefono": perfil.telefono,
                    "area": perfil.area,
                    "cargo": perfil.cargo,
                    "rol": perfil.rol,
                    "activo": instance.is_active and perfil.activo,
                }
            )
        else:
            self.initial.setdefault("rol", PerfilUsuario.Rol.USUARIO)
            self.initial.setdefault("activo", True)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        users = User.objects.filter(username__iexact=username)

        if self.instance:
            users = users.exclude(pk=self.instance.pk)

        if users.exists():
            raise forms.ValidationError("Este nombre de usuario ya existe.")

        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        users = User.objects.filter(email__iexact=email)

        if self.instance:
            users = users.exclude(pk=self.instance.pk)

        if users.exists():
            raise forms.ValidationError(
                "Este correo ya está asociado a otra cuenta."
            )

        return email

    def clean_telefono(self):
        telefono = self.cleaned_data["telefono"].strip()
        digit_count = sum(character.isdigit() for character in telefono)

        if telefono and digit_count < 7:
            raise forms.ValidationError(
                "Escribe un teléfono válido con al menos 7 números."
            )

        return telefono

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1", "")
        password2 = cleaned_data.get("password2", "")

        if not self.is_edit and not password1:
            self.add_error(
                "password1",
                "La contraseña es obligatoria para una cuenta nueva.",
            )
        elif password1:
            if password1 != password2:
                self.add_error("password2", "Las contraseñas no coinciden.")
            else:
                validation_user = self.instance or User(
                    username=cleaned_data.get("username", "")
                )

                try:
                    validate_password(password1, user=validation_user)
                except ValidationError as error:
                    self.add_error("password1", error)

        if self.instance and self.instance.pk == self.actor.pk:
            if not cleaned_data.get("activo"):
                self.add_error(
                    "activo",
                    "No puedes desactivar tu propia cuenta.",
                )

            from .models import PerfilUsuario

            if (
                not self.actor.is_superuser
                and cleaned_data.get("rol") != PerfilUsuario.Rol.ADMIN
            ):
                self.add_error(
                    "rol",
                    "No puedes retirar tu propio rol de administrador.",
                )

        return cleaned_data

    @transaction.atomic
    def save(self):
        from .models import PerfilUsuario

        user = self.instance or User()
        user.username = self.cleaned_data["username"]
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.email = self.cleaned_data["email"]
        user.is_active = self.cleaned_data["activo"]

        if self.cleaned_data["password1"]:
            user.set_password(self.cleaned_data["password1"])

        user.save()

        perfil, _ = PerfilUsuario.objects.get_or_create(user=user)
        perfil.numero_empleado = self.cleaned_data["numero_empleado"].strip()
        perfil.telefono = self.cleaned_data["telefono"]
        perfil.area = self.cleaned_data["area"].strip()
        perfil.cargo = self.cleaned_data["cargo"].strip()
        perfil.rol = self.cleaned_data["rol"]
        perfil.activo = self.cleaned_data["activo"]
        perfil.save()

        actualizar_foto_perfil(
            perfil,
            nueva_foto=self.cleaned_data.get("foto"),
            eliminar=self.cleaned_data.get("eliminar_foto", False),
        )

        return user
