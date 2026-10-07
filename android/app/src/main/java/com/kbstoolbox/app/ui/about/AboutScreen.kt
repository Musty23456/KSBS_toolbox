package com.kbstoolbox.app.ui.about

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import com.kbstoolbox.app.R
import com.kbstoolbox.app.ui.theme.Muted

@Composable
fun AboutScreen(onBack: () -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("About KSBS TOOLBOX") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(padding)
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                "KSBS TOOLBOX is a modern digital toolkit designed to support " +
                    "efficient data collection, management and field operations.",
                style = MaterialTheme.typography.bodyLarge
            )

            Text(
                "Project Creator",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(top = 28.dp)
            )
            Image(
                painter = painterResource(R.drawable.mustapha_salisu),
                contentDescription = "Mustapha Salisu",
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .padding(top = 12.dp)
                    .size(120.dp)
                    .clip(CircleShape)
            )
            Text(
                "Mustapha Salisu",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(top = 12.dp)
            )
            Text(
                "Creator and developer of KSBS TOOLBOX.",
                style = MaterialTheme.typography.bodyMedium,
                color = Muted
            )

            Text(
                "Special Appreciation",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(top = 28.dp)
            )
            Image(
                painter = painterResource(R.drawable.abubakar_suraj),
                contentDescription = "Abubakar Suraj",
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .padding(top = 12.dp)
                    .size(120.dp)
                    .clip(CircleShape)
            )
            Text(
                "Abubakar Suraj",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(top = 12.dp)
            )
            Text(
                "SIWES Coordinator & My Inspirator",
                style = MaterialTheme.typography.bodyMedium,
                color = Muted
            )
            Text(
                "Special thanks to Abubakar Suraj for his guidance, encouragement, " +
                    "support and inspiration throughout the development of this project.",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 8.dp)
            )

            Text(
                "Special Thanks",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(top = 28.dp)
            )
            Text(
                "Special thanks to all KSBS Staff for their support, guidance and contribution.",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 8.dp)
            )

            Text(
                "Development",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(top = 28.dp)
            )
            Text(
                "KSBS TOOLBOX was created by Mustapha Salisu in collaboration with his " +
                    "colleagues and with the assistance of modern Artificial Intelligence.",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 8.dp)
            )

            Text(
                "© 2026 KSBS TOOLBOX",
                style = MaterialTheme.typography.bodyMedium,
                color = Muted,
                modifier = Modifier.padding(top = 28.dp, bottom = 12.dp)
            )
        }
    }
}
