import factory

from apps.accounts.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    moodle_username = factory.Sequence(lambda n: f"student{n}")
    full_name = factory.Faker("name")
    email = factory.Faker("email")
    language = User.Language.AR
    timezone = "Africa/Cairo"
