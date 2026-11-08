package com.kbstoolbox.app.ui.auth

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.kbstoolbox.app.di.ServiceLocator
import com.kbstoolbox.app.ui.theme.FieldGreen
import com.kbstoolbox.app.ui.theme.FieldGreenDark
import com.kbstoolbox.app.ui.theme.Ochre
import com.kbstoolbox.app.util.ViewModelFactory
import androidx.compose.ui.platform.LocalContext

@Composable
fun LoginScreen(onLoginSuccess: () -> Unit, onNavigateToRegister: () -> Unit) {
    val context = LocalContext.current
    val viewModel: LoginViewModel = viewModel(
        factory = ViewModelFactory { LoginViewModel(ServiceLocator.authRepository(context)) }
    )
    val state by viewModel.uiState.collectAsState()

    LaunchedEffect(state.loginSucceeded) {
        if (state.loginSucceeded) onLoginSuccess()
    }

    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        listOf(Color(0xFF061923), Color(0xFF0A3340), Color(0xFF071D2B))
                    )
                )
                .padding(padding)
                .padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(24.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White.copy(alpha = 0.97f)),
                elevation = CardDefaults.cardElevation(defaultElevation = 14.dp)
            ) {
                Column(modifier = Modifier.padding(28.dp)) {
                    Text(
                        "KSBS TOOLBOX",
                        style = MaterialTheme.typography.headlineMedium,
                        color = FieldGreenDark,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        "Smart field data collection & management",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color(0xFF64776F),
                        modifier = Modifier.padding(top = 5.dp)
                    )
                    Spacer(Modifier.height(24.dp))

                    OutlinedTextField(
                        value = state.email,
                        onValueChange = viewModel::onEmailChange,
                        label = { Text("Email") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = state.password,
                        onValueChange = viewModel::onPasswordChange,
                        label = { Text("Password") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        modifier = Modifier.fillMaxWidth()
                    )

                    state.error?.let {
                        Text(
                            text = it,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.padding(top = 12.dp)
                        )
                    }

                    Button(
                        onClick = { viewModel.submit() },
                        enabled = !state.isSubmitting,
                        modifier = Modifier.fillMaxWidth().padding(top = 20.dp),
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = FieldGreen)
                    ) {
                        if (state.isSubmitting) {
                            CircularProgressIndicator(
                                modifier = Modifier.height(20.dp),
                                color = Color.White,
                                strokeWidth = 2.dp
                            )
                        } else {
                            Text("Sign in")
                        }
                    }

                    TextButton(
                        onClick = onNavigateToRegister,
                        modifier = Modifier.fillMaxWidth().padding(top = 4.dp)
                    ) {
                        Text("Create a new account", color = FieldGreenDark)
                    }
                }
            }

            Text(
                "KSBS • Data with purpose",
                color = Color.White.copy(alpha = 0.70f),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 18.dp)
            )
        }
    }
}
