from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAtelierOrdre(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.AtelierOrdre = cls.env['atelier.ordre']
        cls.AtelierOrdreLigne = cls.env['atelier.ordre.ligne']
        cls.Product = cls.env['product.product']
        cls.Partner = cls.env['res.partner']
        cls.SaleOrder = cls.env['sale.order']

        # Création de matières premières avec coût standard
        cls.matiere_bois = cls.Product.create({
            'name': 'Planche de chêne',
            'type': 'consu',
            'standard_price': 25.0,
        })
        cls.matiere_vis = cls.Product.create({
            'name': 'Boîte de vis',
            'type': 'consu',
            'standard_price': 10.0,
        })

        # Création d'un produit fini fabriqué à l'atelier
        cls.produit_atelier = cls.Product.create({
            'name': 'Table sur mesure',
            'type': 'consu',
            'list_price': 350.0,
            'fabrique_atelier': True,
        })

        # Création d'un produit standard non fabriqué à l'atelier
        cls.produit_standard = cls.Product.create({
            'name': 'Chaise standard',
            'type': 'consu',
            'list_price': 80.0,
            'fabrique_atelier': False,
        })

        # Client de test
        cls.client = cls.Partner.create({
            'name': 'Client Test Atelier',
        })

    def test_01_calcul_cout_total(self):
        """Vérifie le calcul automatique de sous_total et cout_total sur l'ordre."""
        ordre = self.AtelierOrdre.create({
            'name': 'ORD-TEST-001',
        })

        # Ajout de 2 lignes : (3 * 25.0) + (2 * 10.0) = 75.0 + 20.0 = 95.0
        ligne_1 = self.AtelierOrdreLigne.create({
            'ordre_id': ordre.id,
            'product_id': self.matiere_bois.id,
            'quantite': 3.0,
        })
        ligne_2 = self.AtelierOrdreLigne.create({
            'ordre_id': ordre.id,
            'product_id': self.matiere_vis.id,
            'quantite': 2.0,
        })

        self.assertEqual(ligne_1.prix_unitaire, 25.0, "Le prix unitaire doit reprendre le coût standard.")
        self.assertEqual(ligne_1.sous_total, 75.0, "Le sous-total de la ligne 1 doit être 75.0.")
        self.assertEqual(ligne_2.sous_total, 20.0, "Le sous-total de la ligne 2 doit être 20.0.")
        self.assertEqual(ordre.cout_total, 95.0, "Le coût total de l'ordre doit être la somme des lignes (95.0).")

        # Vérification du recalcul lors de la modification d'une quantité
        ligne_1.quantite = 4.0  # 4 * 25.0 + 20.0 = 120.0
        self.assertEqual(ordre.cout_total, 120.0, "Le coût total doit se mettre à jour à 120.0.")

    def test_02_contrainte_dates(self):
        """Vérifie que date_livraison_prevue < date_debut lève une ValidationError."""
        date_debut = datetime(2026, 11, 15, 10, 0, 0)
        date_livraison_invalide = date_debut - timedelta(days=1)
        date_livraison_valide = date_debut + timedelta(days=2)

        # Cas invalide : livraison antérieure au début
        with self.assertRaises(ValidationError):
            self.AtelierOrdre.create({
                'name': 'ORD-TEST-DATE-KO',
                'date_debut': date_debut,
                'date_livraison_prevue': date_livraison_invalide,
            })

        # Cas valide : livraison postérieure au début
        ordre_valide = self.AtelierOrdre.create({
            'name': 'ORD-TEST-DATE-OK',
            'date_debut': date_debut,
            'date_livraison_prevue': date_livraison_valide,
        })
        self.assertEqual(ordre_valide.date_livraison_prevue, date_livraison_valide)

    def test_03_creation_automatique_depuis_commande_client(self):
        """Vérifie la création automatique d'un ordre d'atelier à la confirmation d'un devis."""
        # 1. Commande contenant uniquement un produit standard -> aucun ordre créé
        commande_standard = self.SaleOrder.create({
            'partner_id': self.client.id,
            'order_line': [
                (0, 0, {
                    'product_id': self.produit_standard.id,
                    'product_uom_qty': 2.0,
                }),
            ],
        })
        commande_standard.action_confirm()
        self.assertEqual(
            len(commande_standard.atelier_ordre_ids),
            0,
            "Aucun ordre d'atelier ne doit être créé pour un produit standard.",
        )

        # 2. Commande contenant un produit fabriqué à l'atelier -> 1 ordre créé et lié
        commande_atelier = self.SaleOrder.create({
            'partner_id': self.client.id,
            'order_line': [
                (0, 0, {
                    'product_id': self.produit_atelier.id,
                    'product_uom_qty': 1.0,
                }),
            ],
        })
        commande_atelier.action_confirm()

        self.assertEqual(
            commande_atelier.atelier_ordre_count,
            1,
            "Un ordre d'atelier doit être créé automatiquement à la confirmation.",
        )
        ordre_cree = commande_atelier.atelier_ordre_ids[0]
        self.assertEqual(ordre_cree.sale_order_id, commande_atelier)
        self.assertEqual(ordre_cree.state, 'draft')

    def test_04_workflow_et_blocage_modification(self):
        """Vérifie les contrôles du workflow et l'interdiction de modifier un ordre terminé."""
        ordre = self.AtelierOrdre.create({
            'name': 'ORD-TEST-WF',
        })
        ordre.action_demarrer()
        self.assertEqual(ordre.state, 'in_progress')

        # Impossible de terminer sans ligne de matière première
        with self.assertRaises(UserError):
            ordre.action_terminer()

        # Ajout d'une ligne puis clôture réussie
        self.AtelierOrdreLigne.create({
            'ordre_id': ordre.id,
            'product_id': self.matiere_bois.id,
            'quantite': 1.0,
        })
        ordre.action_terminer()
        self.assertEqual(ordre.state, 'done')

        # Impossible de modifier ou supprimer un ordre terminé
        with self.assertRaises(UserError):
            ordre.write({'priorite': '3'})

        with self.assertRaises(UserError):
            ordre.unlink()
