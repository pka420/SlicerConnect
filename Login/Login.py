import logging
import os
import qt
import re
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import threading

try:
    import requests
except ImportError:
    slicer.util.pip_install("requests")
    import requests

class Login(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "SlicerConnect Login"
        self.parent.categories = ["Utilities"]
        self.parent.dependencies = []
        self.parent.contributors = ["Piyush Khurana"]


class LoginWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        uiWidget = slicer.util.loadUI(self.resourcePath("UI/Login.ui"))
        spinnerPath = self.resourcePath("UI/spinner.gif")
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        self.logic = LoginLogic()

        self.ui.registerButton.clicked.connect(self.onRegister)
        self.ui.loginButton.clicked.connect(self.onLogin)
        self.ui.switchToLoginButton.clicked.connect(lambda: self.ui.stackedWidget.setCurrentIndex(0))
        self.ui.switchToRegisterButton.clicked.connect(lambda: self.ui.stackedWidget.setCurrentIndex(1))

        self.ui.stackedWidget.setCurrentIndex(0)
        self.ui.statusLabel.text = ""

        self.ui.loginSpinner = qt.QLabel()
        self.ui.loginSpinner.setAlignment(qt.Qt.AlignCenter)
        self.ui.loginMovie = qt.QMovie(spinnerPath)
        self.ui.loginSpinner.setMovie(self.ui.loginMovie)
        self.ui.loginMovie.setScaledSize(qt.QSize(40, 40))
        self.ui.loginSpinner.hide()
        self.ui.loginButtonLayout.addWidget(self.ui.loginSpinner)
        
        self.ui.registerSpinner = qt.QLabel()
        self.ui.registerSpinner.setAlignment(qt.Qt.AlignCenter)
        self.ui.registerMovie = qt.QMovie(spinnerPath)
        self.ui.registerSpinner.setMovie(self.ui.registerMovie)
        self.ui.registerMovie.setScaledSize(qt.QSize(40, 40))
        self.ui.registerSpinner.hide()
        self.ui.registerButtonLayout.addWidget(self.ui.registerSpinner)

        self.ui.loginButton.enabled = False 
        self.ui.loginEmail.connect('textChanged(QString)', self.validateLoginForm)
        self.ui.loginPassword.connect('textChanged(QString)', self.validateLoginForm)

    def validateLoginForm(self, text):
        email_text = self.ui.loginEmail.text
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        is_email_valid = re.match(email_regex, email_text) is not None
        is_password_valid = len(self.ui.loginPassword.text) >= 8
        self.ui.loginButton.enabled = is_email_valid and is_password_valid 

    def setLoginLoading(self, loading):
        """Toggle login loading state"""
        if loading:
            self.ui.loginButton.setEnabled(False)
            self.ui.loginSpinner.show()
            self.ui.loginMovie.start()
        else:
            self.ui.loginButton.setEnabled(True)
            self.ui.loginSpinner.hide()
            self.ui.loginMovie.stop()
    
    def setRegisterLoading(self, loading):
        """Toggle register loading state"""
        if loading:
            self.ui.registerButton.setEnabled(False)
            self.ui.registerSpinner.show()
            self.ui.registerMovie.start()
        else:
            self.ui.registerButton.setEnabled(True)
            self.ui.registerSpinner.hide()
            self.ui.registerMovie.stop()
    

    def _update_ui(self, status_message=None, switch_to_login=False):
        """Helper to safely update UI on main thread"""
        if status_message is not None:
            self.ui.statusLabel.setText(status_message)
        if switch_to_login:
            self.ui.stackedWidget.setCurrentIndex(0)

    def onRegister(self):
        username = self.ui.regUsername.text.strip()
        email = self.ui.regEmail.text.strip()
        password = self.ui.regPassword.text

        if not all([username, email, password]):
            self.ui.statusLabel.text = "All fields are required."
            return

        self._update_ui("Registering...", False)
        self.setRegisterLoading(True)

        def callback(success, message):
            self.setRegisterLoading(False)
            if success: 
                self.ui.regUsername.setText("")
                self.ui.regEmail.setText("")
                self.ui.regPassword.setText("")
            self._update_ui(message, success)

        threading.Thread(
            target=self.logic.register,
            args=(username, email, password, callback),
            daemon=True
        ).start()

    def onLogin(self):
        email = self.ui.loginEmail.text.strip()
        password = self.ui.loginPassword.text

        self._update_ui("Logging in...")
        self.setLoginLoading(True)

        def callback(success, message, token):
            self.setLoginLoading(False)
            if success:
                slicer.app.settings().setValue("SlicerConnect/Token", token)
                slicer.app.settings().sync()
                self.ui.loginEmail.setText("")
                self.ui.loginPassword.setText("")
                self.ui.regPassword.setText("")
                self._update_ui("Login successful")
                slicer.util.selectModule("SyncData")
            else:
                self._update_ui(message)

        threading.Thread(
            target=self.logic.login,
            args=(email, password, callback),
            daemon=True
        ).start()

class LoginLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        super().__init__()
        self.base_url = "https://slicerconnect.from-delhi.net"

    def register(self, username, email, password, callback):
        try:
            url = f"{self.base_url}/auth/register"
            payload = {
                "username": username,
                "email": email,
                "password": password
            }
            response = requests.post(url, json=payload, timeout=4.0)
            if response.status_code in (200, 201):
                callback(True, response.text)
            else:
                error_msg = response.json().get("detail", response.text or "Unknown error")
                callback(False, f"Registration failed: {error_msg}")
        except requests.Timeout:
            callback(False, "Registration timed out (4 seconds).")
        except requests.ConnectionError:
            callback(False, "Connection failed. Check network or server URL.")
        except requests.HTTPError as e:
            callback(False, f"Server error: {str(e)}")
        except Exception as e:
            callback(False, f"Unexpected error: {str(e)}")

    def login(self, email, password, callback):
        try:
            url = f"{self.base_url}/auth/login"
            payload = {
                "email": email,
                "password": password
            }
            headers = {
                "Content-Type": "application/json",
            }
            response = requests.post(url, json=payload, headers=headers)
            try:
                response.raise_for_status()
            except requests.HTTPError:
                try:
                    data = response.json()
                    msg = data.get("detail") or data.get("message") or response.text
                except Exception:
                    msg = response.text or "Login failed"

                callback(False, msg, None)
                return

            data = response.json()
            token = data.get("access_token") or data.get("token")

            if not token:
                callback(False, "No token returned by server", None)
                return

            callback(True, "Login successful", token)

        except requests.Timeout:
            callback(False, "Login timed out (4s)", None)

        except requests.ConnectionError:
            callback(False, "Cannot connect to server", None)

        except Exception as e:
            callback(False, f"Unexpected error: {e}", None)


