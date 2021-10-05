import logging
from collections import OrderedDict

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView
from django.views.generic import FormView
from django.views.generic import ListView
from django.views.generic import View
from django.views.generic.base import RedirectView
from django.views.generic.detail import SingleObjectMixin

from .coinify import create_coinify_invoice
from .coinify import process_coinify_invoice_json
from .coinify import save_coinify_callback
from .epay import calculate_epay_hash
from .epay import validate_epay_callback
from .forms import OrderProductRelationForm
from .forms import OrderProductRelationFormSet
from shop.models import CreditNote
from shop.models import EpayCallback
from shop.models import EpayPayment
from shop.models import Order
from shop.models import OrderProductRelation
from shop.models import Product
from shop.models import ProductCategory
from vendor.coinify.coinify_callback import CoinifyCallback

logger = logging.getLogger("bornhack.%s" % __name__)


# Mixins
class EnsureCreditNoteHasPDFMixin(SingleObjectMixin):
    model = CreditNote

    def dispatch(self, request, *args, **kwargs):
        if not self.get_object().pdf:
            messages.error(request, "This creditnote has no PDF yet!")
            return HttpResponseRedirect(reverse_lazy("shop:creditnote_list"))

        return super().dispatch(request, *args, **kwargs)


class EnsureUserOwnsCreditNoteMixin(SingleObjectMixin):
    model = CreditNote

    def dispatch(self, request, *args, **kwargs):
        # If the user does not own this creditnote OR is not staff
        if not request.user.is_staff:
            if self.get_object().user != request.user:
                raise Http404("CreditNote not found")

        return super().dispatch(request, *args, **kwargs)


class EnsureUserOwnsOrderMixin(SingleObjectMixin):
    model = Order

    def dispatch(self, request, *args, **kwargs):
        # If the user does not own this order OR is not staff
        if not request.user.is_staff:
            if self.get_object().user != request.user:
                raise Http404("Order not found")

        return super().dispatch(request, *args, **kwargs)


class EnsureUnpaidOrderMixin(SingleObjectMixin):
    model = Order

    def dispatch(self, request, *args, **kwargs):
        if self.get_object().paid:
            messages.error(request, "This order is already paid for!")
            return HttpResponseRedirect(
                reverse_lazy("shop:order_detail", kwargs={"pk": self.get_object().pk}),
            )

        return super().dispatch(request, *args, **kwargs)


class EnsurePaidOrderMixin(SingleObjectMixin):
    model = Order

    def dispatch(self, request, *args, **kwargs):
        if not self.get_object().paid:
            messages.error(request, "This order is not paid for!")
            return HttpResponseRedirect(
                reverse_lazy("shop:order_detail", kwargs={"pk": self.get_object().pk}),
            )

        return super().dispatch(request, *args, **kwargs)


class EnsureClosedOrderMixin(SingleObjectMixin):
    model = Order

    def dispatch(self, request, *args, **kwargs):
        if self.get_object().open is not None:
            messages.error(request, "This order is still open!")
            return HttpResponseRedirect(
                reverse_lazy("shop:order_detail", kwargs={"pk": self.get_object().pk}),
            )

        return super().dispatch(request, *args, **kwargs)


class EnsureOrderHasProductsMixin(SingleObjectMixin):
    model = Order

    def dispatch(self, request, *args, **kwargs):
        if not self.get_object().products.count() > 0:
            messages.error(request, "This order has no products!")
            return HttpResponseRedirect(reverse_lazy("shop:index"))

        return super().dispatch(request, *args, **kwargs)


class EnsureOrderIsNotCancelledMixin(SingleObjectMixin):
    model = Order

    def dispatch(self, request, *args, **kwargs):
        if self.get_object().cancelled:
            messages.error(
                request,
                f"Order #{self.get_object().id} is cancelled!",
            )
            return HttpResponseRedirect(reverse_lazy("shop:index"))

        return super().dispatch(request, *args, **kwargs)


# Shop views
class ShopIndexView(ListView):
    model = Product
    template_name = "shop_index.html"
    context_object_name = "products"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.available().order_by(
            "category__weight",
            "category__name",
            "price",
            "name",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if "category" in self.request.GET:
            category = self.request.GET.get("category")

            # is this a public category
            try:
                categoryobj = ProductCategory.objects.get(slug=category)
                if not categoryobj.public:
                    raise Http404("Category not found")
            except ProductCategory.DoesNotExist:
                raise Http404("Category not found")

            # filter products by the chosen category
            context["products"] = context["products"].filter(category__slug=category)
            context["current_category"] = categoryobj
        context["categories"] = ProductCategory.objects.annotate(
            num_products=Count("products"),
        ).filter(
            num_products__gt=0,
            public=True,
            products__available_in__contains=timezone.now(),
        )
        return context


class ProductDetailView(FormView, DetailView):
    model = Product
    template_name = "product_detail.html"
    form_class = OrderProductRelationForm
    context_object_name = "product"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if hasattr(self, "opr"):
            kwargs["instance"] = self.opr
        return kwargs

    def get_initial(self):
        if hasattr(self, "opr"):
            return {"quantity": self.opr.quantity}
        return None

    def get_context_data(self, **kwargs):
        # If the OrderProductRelation already exists it has a primary key in the database
        if self.request.user.is_authenticated and self.opr.pk:
            kwargs["already_in_order"] = True

        return super().get_context_data(**kwargs)

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()

        if not self.object.category.public:
            # this product is not publicly available
            raise Http404("Product not found")

        if self.request.user.is_authenticated:
            try:
                self.opr = OrderProductRelation.objects.get(
                    order__user=self.request.user,
                    order__open__isnull=False,
                    product=self.object,
                )
            except OrderProductRelation.DoesNotExist:
                self.opr = OrderProductRelation(product=self.get_object(), quantity=1)

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        opr = form.save(commit=False)

        if not opr.pk:
            opr.order, _ = Order.objects.get_or_create(
                user=self.request.user,
                open=True,
                cancelled=False,
            )

        opr.save()

        messages.info(
            self.request,
            "{}x {} has been added to your order.".format(
                opr.quantity,
                opr.product.name,
            ),
        )

        # done
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("shop:index")


class OrderListView(LoginRequiredMixin, ListView):
    model = Order
    template_name = "order_list.html"
    context_object_name = "orders"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(user=self.request.user).not_cancelled()


class OrderDetailView(
    LoginRequiredMixin,
    EnsureUserOwnsOrderMixin,
    EnsureOrderHasProductsMixin,
    EnsureOrderIsNotCancelledMixin,
    DetailView,
):
    model = Order
    context_object_name = "order"

    def get_context_data(self, **kwargs):
        if "order_product_formset" not in kwargs:
            kwargs["order_product_formset"] = OrderProductRelationFormSet(
                queryset=OrderProductRelation.objects.filter(order=self.get_object()),
            )

        return super().get_context_data(**kwargs)

    def get_template_names(self):
        if self.get_object().open is None:
            return "order_detail_closed.html"
        elif self.get_object().open is True:
            return "order_detail_open.html"
        else:
            return False

    def get(self, request, *args, **kwargs):
        order = self.get_object()
        if order.open is None and not order.paid:
            # order is already closed, go straight to the payment page
            return HttpResponseRedirect(
                reverse("shop:order_review_and_pay", kwargs={"pk": order.pk}),
            )
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """The main webshop order handling method.

        Start out by handling two special cases, deleting OPR and
        cancelling orders, before creating a formset with the POST data.

        The formset validation checks stock amounts. If no stock issues are
        found the formset (meaning OPRs) is saved.

        Then the user is redirected either back to the order page or to the
        payment page, depending on which submit button was pressed.
        """
        self.object = self.get_object()
        order = self.object

        # First check if the user is removing a product from the order.
        product_remove = request.POST.get("remove_product")
        if product_remove:
            order.oprs.filter(pk=product_remove).delete()
            if not order.products.count() > 0:
                order.mark_as_cancelled()
                messages.info(request, "There is no spoon. Order cancelled!")
                return HttpResponseRedirect(reverse_lazy("shop:index"))

        # Then see if the user is cancelling the order.
        elif "cancel_order" in request.POST:
            order.mark_as_cancelled()
            messages.info(request, "Order cancelled!")
            return HttpResponseRedirect(reverse_lazy("shop:index"))

        # The user is not removing products or cancelling the order,
        # so from now on we do stuff that require us to check stock.
        # We use a formset for this to be able to display exactly
        # which product is not in stock if that is the case.
        else:
            formset = OrderProductRelationFormSet(
                request.POST,
                queryset=OrderProductRelation.objects.filter(order=order),
            )

            # If the formset is not valid it means that we cannot fulfill the order,
            # so show a message and redirect the user back to the order detail page
            if not formset.is_valid():
                messages.error(
                    request,
                    "Some of the products you are ordering are out of stock. Review the order and try again.",
                )
                return HttpResponseRedirect(
                    reverse("shop:order_detail", kwargs={"pk": order.pk})
                )

            # No stock issues, proceed to save OPRs and Order
            if "update_order" or "review_and_pay" in request.POST:
                # We have already made sure the formset is valid, so just save it to update quantities.
                formset.save()

                order.customer_comment = request.POST.get("customer_comment") or ""
                order.invoice_address = request.POST.get("invoice_address") or ""
                order.save()

            if "review_and_pay" in request.POST:
                # user is ready to pay, redirect
                return HttpResponseRedirect(
                    reverse("shop:order_review_and_pay", kwargs={"pk": order.pk})
                )

        # redirect remaining cases back to the order page
        return HttpResponseRedirect(
            reverse("shop:order_detail", kwargs={"pk": order.pk})
        )


class OrderReviewAndPayView(
    LoginRequiredMixin,
    EnsureUserOwnsOrderMixin,
    EnsureOrderHasProductsMixin,
    EnsureUnpaidOrderMixin,
    EnsureOrderIsNotCancelledMixin,
    DetailView,
):
    template_name = "order_review.html"
    context_object_name = "order"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        order = self.object

        payment_method = request.POST.get("payment_method")
        if payment_method in order.PAYMENT_METHODS:
            if not request.POST.get("accept_terms"):
                messages.error(
                    request,
                    "You need to accept the general terms and conditions before you can continue!",
                )
                return self.render_to_response(self.get_context_data())

            # Set payment method and mark the order as closed
            order.payment_method = payment_method
            order.open = None
            order.save()

            reverses = {
                Order.CREDIT_CARD: reverse_lazy(
                    "shop:epay_form",
                    kwargs={"pk": order.id},
                ),
                Order.BLOCKCHAIN: reverse_lazy(
                    "shop:coinify_pay",
                    kwargs={"pk": order.id},
                ),
                Order.BANK_TRANSFER: reverse_lazy(
                    "shop:bank_transfer",
                    kwargs={"pk": order.id},
                ),
                Order.IN_PERSON: reverse_lazy(
                    "shop:in_person",
                    kwargs={"pk": order.id},
                ),
            }

            return HttpResponseRedirect(reverses[payment_method])


class DownloadInvoiceView(
    LoginRequiredMixin,
    EnsureUserOwnsOrderMixin,
    SingleObjectMixin,
    View,
):
    model = Order

    def get(self, request, *args, **kwargs):
        """
        The file we return is determined by the orders paid status.
        If the order is unpaid we return a proforma invoice PDF
        If the order is paid we return a normal Invoice PDF
        """
        if self.get_object().paid:
            pdfobj = self.get_object().invoice
        else:
            pdfobj = self.get_object()

        if not pdfobj.pdf:
            messages.error(request, "No PDF has been generated yet!")
            return HttpResponseRedirect(
                reverse_lazy("shop:order_detail", kwargs={"pk": self.get_object().pk}),
            )
        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="%s"' % pdfobj.filename
        response.write(pdfobj.pdf.read())
        return response


class CreditNoteListView(LoginRequiredMixin, ListView):
    model = CreditNote
    template_name = "creditnote_list.html"
    context_object_name = "creditnotes"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(user=self.request.user)


class DownloadCreditNoteView(
    LoginRequiredMixin,
    EnsureUserOwnsCreditNoteMixin,
    EnsureCreditNoteHasPDFMixin,
    SingleObjectMixin,
    View,
):
    model = CreditNote

    def get(self, request, *args, **kwargs):
        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = (
            'attachment; filename="%s"' % self.get_object().filename
        )
        response.write(self.get_object().pdf.read())
        return response


class OrderMarkAsPaidView(LoginRequiredMixin, SingleObjectMixin, View):

    model = Order

    def get(self, request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, "You do not have permissions to do that.")
            return HttpResponseRedirect(reverse_lazy("shop:index"))
        else:
            messages.success(request, "The order has been marked as paid.")
            order = self.get_object()
            order.mark_as_paid()
            return HttpResponseRedirect(request.headers.get("Referer"))


# Epay views
class EpayFormView(
    LoginRequiredMixin,
    EnsureUserOwnsOrderMixin,
    EnsureUnpaidOrderMixin,
    EnsureClosedOrderMixin,
    EnsureOrderHasProductsMixin,
    DetailView,
):
    model = Order
    template_name = "epay_form.html"

    def get_context_data(self, **kwargs):
        order = self.get_object()
        context = super().get_context_data(**kwargs)
        context["merchant_number"] = settings.EPAY_MERCHANT_NUMBER
        context["description"] = order.description
        context["amount"] = order.total * 100
        context["order_id"] = order.pk
        context["accept_url"] = order.get_epay_accept_url(self.request)
        context["cancel_url"] = order.get_cancel_url(self.request)
        context["callback_url"] = order.get_epay_callback_url(self.request)
        context["epay_hash"] = calculate_epay_hash(order, self.request)
        return context


class EpayCallbackView(SingleObjectMixin, View):
    model = Order

    def get(self, request, *args, **kwargs):
        callback = EpayCallback.objects.create(payload=request.GET)

        if "orderid" in request.GET:
            query = OrderedDict(
                [tuple(x.split("=")) for x in request.META["QUERY_STRING"].split("&")],
            )
            order = get_object_or_404(Order, pk=query.get("orderid"))
            if order.pk != self.get_object().pk:
                logger.error("bad epay callback, orders do not match!")
                return HttpResponse(status=400)

            if validate_epay_callback(query):
                callback.md5valid = True
                callback.save()
            else:
                logger.error("bad epay callback!")
                return HttpResponse(status=400)

            if order.paid:
                # this order is already paid, perhaps we are seeing a double callback?
                return HttpResponse("OK")

            # epay callback is valid - has the order been paid in full?
            if int(query["amount"]) == order.total * 100:
                # create an EpayPayment object linking the callback to the order
                EpayPayment.objects.create(
                    order=order,
                    callback=callback,
                    txnid=query.get("txnid"),
                )
                # and mark order as paid (this will create tickets)
                order.mark_as_paid(request)
            else:
                logger.error("valid epay callback with wrong amount detected")
        else:
            return HttpResponse(status=400)

        return HttpResponse("OK")


class EpayThanksView(
    LoginRequiredMixin,
    EnsureUserOwnsOrderMixin,
    EnsureClosedOrderMixin,
    DetailView,
):
    model = Order
    template_name = "epay_thanks.html"

    def dispatch(self, request, *args, **kwargs):
        if request.GET:
            # epay redirects the user back to our accepturl with a long
            # and ugly querystring, redirect user to the clean url
            return HttpResponseRedirect(
                reverse("shop:epay_thanks", kwargs={"pk": self.get_object().pk}),
            )

        return super().dispatch(request, *args, **kwargs)


# Bank Transfer view


class BankTransferView(
    LoginRequiredMixin,
    EnsureUserOwnsOrderMixin,
    EnsureUnpaidOrderMixin,
    EnsureOrderHasProductsMixin,
    DetailView,
):
    model = Order
    template_name = "bank_transfer.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["iban"] = settings.BANKACCOUNT_IBAN
        context["swiftbic"] = settings.BANKACCOUNT_SWIFTBIC
        context["orderid"] = self.get_object().pk
        context["regno"] = settings.BANKACCOUNT_REG
        context["accountno"] = settings.BANKACCOUNT_ACCOUNT
        context["total"] = self.get_object().total
        return context


# In-person (izettle) payment view


class PayInPersonView(
    LoginRequiredMixin,
    EnsureUserOwnsOrderMixin,
    EnsureUnpaidOrderMixin,
    EnsureOrderHasProductsMixin,
    DetailView,
):
    model = Order
    template_name = "in_person.html"


# Coinify views


class CoinifyRedirectView(
    LoginRequiredMixin,
    EnsureUserOwnsOrderMixin,
    EnsureUnpaidOrderMixin,
    EnsureClosedOrderMixin,
    EnsureOrderHasProductsMixin,
    SingleObjectMixin,
    RedirectView,
):
    model = Order

    def dispatch(self, request, *args, **kwargs):
        order = self.get_object()

        # create a new coinify invoice if needed
        if not order.coinifyapiinvoice:
            coinifyinvoice = create_coinify_invoice(order, request)
            if not coinifyinvoice:
                messages.error(
                    request,
                    "There was a problem with the payment provider. Please try again later",
                )
                return HttpResponseRedirect(
                    reverse_lazy(
                        "shop:order_detail",
                        kwargs={"pk": self.get_object().pk},
                    ),
                )

        return super().dispatch(request, *args, **kwargs)

    def get_redirect_url(self, *args, **kwargs):
        return self.get_object().coinifyapiinvoice.invoicejson["payment_url"]


class CoinifyCallbackView(SingleObjectMixin, View):
    model = Order

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request, *args, **kwargs):
        # save callback and parse json payload
        callbackobject = save_coinify_callback(request, self.get_object())

        # do we have a json body?
        if not callbackobject.payload:
            # no, return an error
            logger.error(
                "unable to parse JSON body in callback for order %s"
                % callbackobject.order.id,
            )
            return HttpResponseBadRequest("unable to parse json")

        # initiate SDK
        sdk = CoinifyCallback(settings.COINIFY_IPN_SECRET.encode("utf-8"))

        # attemt to validate the callbackc
        if sdk.validate_callback(
            request.body,
            request.headers["X-Coinify-Callback-Signature"],
        ):
            # mark callback as valid in db
            callbackobject.valid = True
            callbackobject.save()
        else:
            logger.error("invalid coinify callback detected")
            return HttpResponseBadRequest("something is fucky")

        if (
            callbackobject.payload["event"] == "invoice_state_change"
            or callbackobject.payload["event"] == "invoice_manual_resend"
        ):
            process_coinify_invoice_json(
                invoicejson=callbackobject.payload["data"],
                order=self.get_object(),
                request=request,
            )
            return HttpResponse("OK")
        else:
            logger.error(
                "unsupported callback event %s" % callbackobject.payload["event"],
            )
            return HttpResponseBadRequest("unsupported event")


class CoinifyThanksView(
    LoginRequiredMixin,
    EnsureUserOwnsOrderMixin,
    EnsureClosedOrderMixin,
    DetailView,
):
    model = Order
    template_name = "coinify_thanks.html"
