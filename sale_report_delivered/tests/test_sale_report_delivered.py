# Copyright 2022 Tecnativa - Víctor Martínez
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.tests import Form, common, new_test_user
from odoo.tests.common import users


class TestSaleReportDeliveredBase(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.admin = cls.env.ref("base.user_admin")
        cls.pricelist = cls.env["product.pricelist"].create(
            {
                "name": "Test pricelist",
                "currency_id": cls.company.currency_id.id,
            }
        )
        cls.partner = cls.env["res.partner"].create(
            {"name": "Test partner", "property_product_pricelist": cls.pricelist.id}
        )
        cls.user = new_test_user(
            cls.env,
            login="test_user-sale_report_delivered",
            name="test_user-one",
            groups="sales_team.group_sale_manager",
        )
        group_sale_manager = cls.env.ref("sales_team.group_sale_manager")
        group_sale_manager.write({"users": [(4, cls.admin.id)]})

        cls.product = cls.env["product.product"].create(
            {
                "name": "Test product",
                "type": "consu",
                "is_storable": True,
                "list_price": 10,
            }
        )
        cls._create_stock_quant(cls, cls.product)
        cls.service = cls.env["product.product"].create(
            {"name": "Test service", "type": "service", "list_price": 10}
        )
        cls.order_1 = cls._create_order(cls, cls.product)
        cls.order_2 = cls._create_order(cls, cls.service)
        cls.orders = cls.order_1 + cls.order_2
        cls.orders.action_confirm()
        cls.orders.picking_ids.action_confirm()
        customer_location = cls.env.ref("stock.stock_location_customers")
        cls.order_1.picking_ids.write({"location_dest_id": customer_location.id})
        cls.order_1.picking_ids.move_ids.write(
            {"location_dest_id": customer_location.id, "quantity": 1.0}
        )
        cls.orders.picking_ids.button_validate()

    def _create_stock_quant(self, product):
        res = product.action_update_quantity_on_hand()
        quant_form = Form(
            self.env["stock.quant"].with_context(**res["context"]),
            view="stock.view_stock_quant_tree_inventory_editable",
        )
        quant_form.inventory_quantity = 1
        quant_form.location_id = self.env.ref("stock.stock_location_stock")
        return quant_form.save()

    def _create_order(self, product):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        with order_form.order_line.new() as line_form:
            line_form.product_id = product
            line_form.product_uom_qty = 1
        return order_form.save()

    def _get_stock_move(self, order):
        sale_line = order.order_line.filtered(
            lambda line: line.product_id == self.product
        )[:1]
        return self.env["stock.move"].search(
            [
                ("sale_line_id", "=", sale_line.id),
                ("product_id", "=", self.product.id),
                ("state", "=", "done"),
            ],
            limit=1,
        )

    def _get_product_sale_line(self, order):
        return order.order_line.filtered(lambda line: line.product_id == self.product)[
            :1
        ]

    def _get_report_items(self, order):
        return self.env["sale.report.delivered"].search(
            [
                ("order_id", "=", order.id),
                ("product_id", "=", self.product.id),
            ]
        )


class TestSaleReportDelivered(TestSaleReportDeliveredBase):
    @users("admin", "test_user-sale_report_delivered")
    def test_sale_report_delivered_misc(self):
        items = self.env["sale.report.delivered"].search(
            [("order_id", "in", self.orders.ids)]
        )
        self.assertIn(self.order_1, items.mapped("order_id"))
        self.assertNotIn(self.order_2, items.mapped("order_id"))
        self.assertIn(self.order_1.picking_ids, items.mapped("picking_id"))
        self.assertIn(self.product, items.mapped("product_id"))
        self.assertNotIn(self.service, items.mapped("product_id"))

    def _test_sale_report_delivered_read_group(self):
        self.product.stock_valuation_layer_ids.value = 1
        res = self.env["sale.report.delivered"].read_group(
            domain=[("order_id", "in", self.orders.ids)],
            fields=[
                "order_id",
                "margin_percent:sum",
                "price_subtotal:sum",
                "margin:sum",
            ],
            groupby=["order_id"],
        )
        self.assertAlmostEqual(res[0]["margin_percent"], 100.00)

    @users("admin")
    def test_sale_report_delivered_read_group_admin(self):
        self._test_sale_report_delivered_read_group()

    @users("test_user-sale_report_delivered")
    def test_sale_report_delivered_read_group(self):
        self._test_sale_report_delivered_read_group()

    @users("admin")
    def test_sale_report_delivered_ignores_revaluation_layer_qty(self):
        move = self._get_stock_move(self.order_1)
        self.assertTrue(move)
        self.env["stock.valuation.layer"].create(
            {
                "company_id": self.company.id,
                "product_id": self.product.id,
                "quantity": 0.0,
                "value": 1.0,
                "remaining_qty": 0.0,
                "remaining_value": 0.0,
                "description": "Manual revaluation",
                "stock_move_id": move.id,
            }
        )
        self.env.flush_all()
        report_item = self._get_report_items(self.order_1)
        sale_line = self._get_product_sale_line(self.order_1)
        self.assertEqual(len(report_item), 1)
        self.assertEqual(report_item.product_uom_qty, 1.0)
        self.assertEqual(report_item.price_subtotal, sale_line.price_subtotal)

    @users("admin")
    def test_sale_report_delivered_excludes_zero_quantity_done_moves(self):
        move = self._get_stock_move(self.order_1)
        self.assertTrue(move)
        self.env["stock.move"].create(
            {
                "name": move.name,
                "company_id": move.company_id.id,
                "product_id": move.product_id.id,
                "product_uom": move.product_uom.id,
                "product_uom_qty": 1.0,
                "quantity": 0.0,
                "location_id": move.location_id.id,
                "location_dest_id": move.location_dest_id.id,
                "picking_id": move.picking_id.id,
                "sale_line_id": move.sale_line_id.id,
                "state": "done",
                "date": "2099-01-01 00:00:00",
                "picked": True,
            }
        )
        self.env.flush_all()
        report_item = self._get_report_items(self.order_1)
        sale_line = self._get_product_sale_line(self.order_1)
        self.assertEqual(len(report_item), 1)
        self.assertEqual(report_item.product_uom_qty, 1.0)
        self.assertEqual(report_item.price_subtotal, sale_line.price_subtotal)
