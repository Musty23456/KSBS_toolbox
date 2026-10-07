package com.kbstoolbox.app.ui.dashboard

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.kbstoolbox.app.di.ServiceLocator
import com.kbstoolbox.app.ui.theme.Brick
import com.kbstoolbox.app.ui.theme.FieldGreen
import com.kbstoolbox.app.ui.theme.Ochre
import com.kbstoolbox.app.util.ViewModelFactory

@Composable
fun DashboardScreen(
    onOpenSurveys: () -> Unit,
    onOpenSubmissions: () -> Unit,
    onOpenAbout: () -> Unit,
    onLogout: () -> Unit
) {
    val context = LocalContext.current
    val viewModel: DashboardViewModel = viewModel(
        factory = ViewModelFactory {
            DashboardViewModel(
                ServiceLocator.sessionManager(context),
                ServiceLocator.surveyRepository(context),
                ServiceLocator.submissionRepository(context),
                ServiceLocator.connectivityObserver(context)
            )
        }
    )
    val state by viewModel.uiState.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(title = { Text("KSBS TOOLBOX") })
        }
    ) { padding ->
        Column(modifier = Modifier
            .fillMaxSize()
            .padding(padding)
            .padding(16.dp)) {

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text("Welcome, ${state.fullName}", style = MaterialTheme.typography.titleLarge)
                    Text(state.role.lowercase().replaceFirstChar { it.uppercase() }, style = MaterialTheme.typography.bodyMedium)
                }
                Text(
                    text = if (state.isOnline) "Online" else "Offline",
                    color = if (state.isOnline) FieldGreen else Ochre,
                    style = MaterialTheme.typography.labelLarge
                )
            }

            LazyVerticalGrid(
                columns = GridCells.Fixed(2),
                modifier = Modifier.padding(top = 20.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(
                    listOf(
                        Triple("Downloaded surveys", state.downloadedSurveys, FieldGreen),
                        Triple("Draft forms", state.draftForms, Ochre),
                        Triple("Pending sync", state.pendingSync, Ochre),
                        Triple("Synced submissions", state.syncedSubmissions, FieldGreen),
                        Triple("Failed sync", state.failedSync, Brick)
                    )
                ) { (label, value, color) ->
                    StatCard(label = label, value = value, accentColor = color)
                }
            }

            state.refreshMessage?.let {
                Text(it, modifier = Modifier.padding(top = 16.dp), style = MaterialTheme.typography.bodyMedium)
            }

            Button(
                onClick = { viewModel.refreshSurveys() },
                enabled = !state.isRefreshing,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 20.dp)
            ) {
                Text(if (state.isRefreshing) "Downloading…" else "Download / refresh surveys")
            }

            Button(
                onClick = onOpenSurveys,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 12.dp)
            ) {
                Text("Fill a survey")
            }

            Button(
    onClick = onOpenAbout,
    modifier = Modifier
        .fillMaxWidth()
        .padding(top = 12.dp)
) {
    Text("About KSBS TOOLBOX")
            }
            Button(
                onClick = onOpenSubmissions,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 12.dp)
            ) {
                Text("My submissions")
            }

            Button(
                onClick = onLogout,
                colors = androidx.compose.material3.ButtonDefaults.buttonColors(containerColor = Color.Transparent),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 24.dp)
            ) {
                Text("Log out", color = Brick)
            }
        }
    }
}

@Composable
private fun StatCard(label: String, value: Int, accentColor: Color) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(text = value.toString(), style = MaterialTheme.typography.headlineMedium, color = accentColor)
            Text(text = label, style = MaterialTheme.typography.bodyMedium)
        }
    }
}
