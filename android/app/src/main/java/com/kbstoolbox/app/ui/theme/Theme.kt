package com.kbstoolbox.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

private val LightColors = lightColorScheme(
    primary = FieldGreen,
    onPrimary = PaperRaised,
    primaryContainer = EmeraldLight,
    onPrimaryContainer = FieldGreenDark,
    secondary = Ochre,
    onSecondary = Ink,
    secondaryContainer = ColorTokens.ochreContainer,
    onSecondaryContainer = ColorTokens.ochreText,
    background = Paper,
    onBackground = Ink,
    surface = PaperRaised,
    onSurface = Ink,
    surfaceVariant = NavyLight,
    onSurfaceVariant = InkSoft,
    error = Brick,
    outline = Hairline
)

private val AppTypography = Typography(
    headlineMedium = TextStyle(fontWeight = FontWeight.Bold, fontSize = 26.sp),
    titleLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 20.sp),
    bodyLarge = TextStyle(fontWeight = FontWeight.Normal, fontSize = 16.sp),
    bodyMedium = TextStyle(fontWeight = FontWeight.Normal, fontSize = 14.sp),
    labelLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
)

private object ColorTokens {
    val ochreContainer = Ochre.copy(alpha = 0.18f)
    val ochreText = Color(0xFF76500F)
}

@Composable
fun KbsToolboxTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = LightColors,
        typography = AppTypography,
        content = content
    )
}
