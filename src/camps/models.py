import logging
from datetime import timedelta

from django.apps import apps
from django.contrib.postgres.fields import DateTimeRangeField
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from psycopg2.extras import DateTimeTZRange

from utils.models import CreatedUpdatedModel, UUIDModel

logger = logging.getLogger("bornhack.%s" % __name__)


class Permission(models.Model):
    """
    An unmanaged field-less model which holds our non-model permissions (such as team permission sets)
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("backoffice_permission", "BackOffice access"),
            ("badgeteam_permission", "Badge Team permissions set"),
            ("barteam_permission", "Bar Team permissions set"),
            ("certteam_permission", "CERT Team permissions set"),
            ("constructionteam_permission", "Construction Team permissions set"),
            ("contentteam_permission", "Content Team permissions set"),
            ("economyteam_permission", "Economy Team permissions set"),
            ("foodareateam_permission", "Foodarea Team permissions set"),
            ("gameteam_permission", "Game Team permissions set"),
            ("infoteam_permission", "Info Team permissions set"),
            ("lightteam_permission", "Light Team permissions set"),
            ("logisticsteam_permission", "Logistics Team permissions set"),
            ("metricsteam_permission", "Metrics Team permissions set"),
            ("nocteam_permission", "NOC Team permissions set"),
            ("orgateam_permission", "Orga Team permissions set"),
            ("pocteam_permission", "POC Team permissions set"),
            ("prteam_permission", "PR Team permissions set"),
            ("phototeam_permission", "Photo Team permissions set"),
            ("powerteam_permission", "Power Team permissions set"),
            ("rocteam_permission", "ROC Team permissions set"),
            ("sanitationteam_permission", "Sanitation Team permissions set"),
            ("shuttleteam_permission", "Shuttle Team permissions set"),
            ("sponsorsteam_permission", "Sponsors Team permissions set"),
            ("sysadminteam_permission", "Sysadmin Team permissions set"),
            ("videoteam_permission", "Video Team permissions set"),
            ("websiteteam_permission", "Website Team permissions set"),
            ("wellnessteam_permission", "Wellness Team permissions set"),
            ("expense_create_permission", "Expense Create permission"),
            ("revenue_create_permission", "Revenue Create permission"),
        )


class Camp(CreatedUpdatedModel, UUIDModel):
    class Meta:
        verbose_name = "Camp"
        verbose_name_plural = "Camps"
        ordering = ["-title"]

    title = models.CharField(
        verbose_name="Title",
        help_text="Title of the camp, ie. Bornhack 2016.",
        max_length=255,
    )

    tagline = models.CharField(
        verbose_name="Tagline",
        help_text='Tagline of the camp, ie. "Initial Commit"',
        max_length=255,
    )

    slug = models.SlugField(
        verbose_name="Url Slug", help_text="The url slug to use for this camp"
    )

    shortslug = models.SlugField(
        verbose_name="Short Slug",
        help_text="Abbreviated version of the slug. Used in IRC channel names and other places with restricted name length.",
    )

    buildup = DateTimeRangeField(
        verbose_name="Buildup Period", help_text="The camp buildup period."
    )

    camp = DateTimeRangeField(verbose_name="Camp Period", help_text="The camp period.")

    teardown = DateTimeRangeField(
        verbose_name="Teardown period", help_text="The camp teardown period."
    )

    read_only = models.BooleanField(
        help_text="Whether the camp is read only (i.e. in the past)", default=False
    )

    colour = models.CharField(
        verbose_name="Colour",
        help_text="The primary colour for the camp in hex",
        max_length=7,
    )

    light_text = models.BooleanField(
        default=True,
        help_text="Check if this camps colour requires white text, uncheck if black text is better",
    )

    call_for_participation_open = models.BooleanField(
        help_text="Check if the Call for Participation is open for this camp",
        default=False,
    )

    call_for_participation = models.TextField(
        blank=True,
        help_text="The CFP markdown for this Camp",
        default="The Call For Participation for this Camp has not been written yet",
    )

    call_for_sponsors_open = models.BooleanField(
        help_text="Check if the Call for Sponsors is open for this camp", default=False
    )

    call_for_sponsors = models.TextField(
        blank=True,
        help_text="The CFS markdown for this Camp",
        default="The Call For Sponsors for this Camp has not been written yet",
    )

    show_schedule = models.BooleanField(
        help_text="Check if the schedule should be shown.", default=True
    )

    def get_absolute_url(self):
        return reverse("camp_detail", kwargs={"camp_slug": self.slug})

    def clean(self):
        """Make sure the dates make sense - meaning no overlaps and buildup before camp before teardown"""
        errors = []
        # check for overlaps buildup vs. camp
        if self.buildup.upper > self.camp.lower:
            msg = "End of buildup must not be after camp start"
            errors.append(ValidationError({"buildup", msg}))
            errors.append(ValidationError({"camp", msg}))

        # check for overlaps camp vs. teardown
        if self.camp.upper > self.teardown.lower:
            msg = "End of camp must not be after teardown start"
            errors.append(ValidationError({"camp", msg}))
            errors.append(ValidationError({"teardown", msg}))

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return "%s - %s" % (self.title, self.tagline)

    @property
    def logo_small(self):
        return "img/%(slug)s/logo/%(slug)s-logo-s.png" % {"slug": self.slug}

    @property
    def logo_small_svg(self):
        return "img/%(slug)s/logo/%(slug)s-logo-small.svg" % {"slug": self.slug}

    @property
    def logo_large(self):
        return "img/%(slug)s/logo/%(slug)s-logo-l.png" % {"slug": self.slug}

    @property
    def logo_large_svg(self):
        return "img/%(slug)s/logo/%(slug)s-logo-large.svg" % {"slug": self.slug}

    def get_days(self, camppart):
        """
        Returns a list of DateTimeTZRanges representing the days during the specified part of the camp.
        """
        if not hasattr(self, camppart):
            logger.error("nonexistant field/attribute")
            return False

        field = getattr(self, camppart)

        if (
            not hasattr(field, "__class__")
            or not hasattr(field.__class__, "__name__")
            or not field.__class__.__name__ == "DateTimeTZRange"
        ):
            logger.error("this attribute is not a datetimetzrange field: %s" % field)
            return False

        # count how many unique dates we have in this range
        daycount = 1
        while True:
            if field.lower.date() + timedelta(days=daycount) > field.upper.date():
                break
            daycount += 1

        # loop through the required number of days, append to list as we go
        days = []
        for i in range(0, daycount):
            if i == 0:
                # on the first day use actual start time instead of midnight (local time)
                days.append(
                    DateTimeTZRange(
                        timezone.localtime(field.lower),
                        timezone.localtime(
                            (field.lower + timedelta(days=i + 1))
                        ).replace(hour=0),
                    )
                )
            elif i == daycount - 1:
                # on the last day use actual end time instead of midnight (local time)
                days.append(
                    DateTimeTZRange(
                        timezone.localtime((field.lower + timedelta(days=i))).replace(
                            hour=0
                        ),
                        timezone.localtime(field.lower + timedelta(days=i)),
                    )
                )
            else:
                # neither first nor last day, goes from midnight to midnight (local time)
                days.append(
                    DateTimeTZRange(
                        timezone.localtime((field.lower + timedelta(days=i))).replace(
                            hour=0
                        ),
                        timezone.localtime(
                            (field.lower + timedelta(days=i + 1))
                        ).replace(hour=0),
                    )
                )
        return days

    @property
    def buildup_days(self):
        """
        Returns a list of DateTimeTZRanges representing the days during the buildup.
        """
        return self.get_days("buildup")

    @property
    def camp_days(self):
        """
        Returns a list of DateTimeTZRanges representing the days during the camp.
        """
        return self.get_days("camp")

    @property
    def teardown_days(self):
        """
        Returns a list of DateTimeTZRanges representing the days during the buildup.
        """
        return self.get_days("teardown")

    # convenience properties to access Camp-related stuff easily from the Camp object

    @property
    def event_types(self):
        """Return all event types with at least one event in this camp"""
        EventType = apps.get_model("program", "EventType")
        return EventType.objects.filter(
            events__isnull=False, event__track__camp=self
        ).distinct()

    @property
    def event_proposals(self):
        EventProposal = apps.get_model("program", "EventProposal")
        return EventProposal.objects.filter(track__camp=self)

    @property
    def events(self):
        Event = apps.get_model("program", "Event")
        return Event.objects.filter(track__camp=self)

    @property
    def event_sessions(self):
        EventSession = apps.get_model("program", "EventSession")
        return EventSession.objects.filter(camp=self)

    @property
    def event_slots(self):
        EventSlot = apps.get_model("program", "EventSlot")
        return EventSlot.objects.filter(event_session__in=self.event_sessions.all())
