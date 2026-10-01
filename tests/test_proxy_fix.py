import unittest
from app import create_app


class ProxyFixTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'WTF_CSRF_ENABLED': False,
        })
        self.client = self.app.test_client()

    def test_proxy_fix_reconoce_esquema_https_desde_proxy(self):
        @self.app.route('/test-scheme')
        def test_scheme():
            from flask import request
            return {'scheme': request.scheme, 'is_secure': request.is_secure}

        response = self.client.get('/test-scheme', headers={'X-Forwarded-Proto': 'https'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['scheme'], 'https')
        self.assertTrue(response.json['is_secure'])

    def test_proxy_fix_reconoce_host_desde_proxy(self):
        @self.app.route('/test-host')
        def test_host():
            from flask import request
            return {'host': request.host}

        response = self.client.get('/test-host', headers={'X-Forwarded-Host': 'panel.sena.edu.co'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['host'], 'panel.sena.edu.co')


if __name__ == '__main__':
    unittest.main()
